using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using FraudDetection.API.Controllers;
using FraudDetection.Application.Commands.ValidateAlert;
using FraudDetection.Infrastructure.Auth;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.IdentityModel.Tokens;
using Xunit;

namespace FraudDetection.Tests.API;

/// <summary>
/// Vérifie les deux correctifs découverts en préparant le pack de démarrage
/// frontend — jamais testés avant car les tests précédents passaient par
/// MediatR directement, jamais par une vraie désérialisation JSON HTTP
/// ni un vrai pipeline d'authentification JWT.
/// </summary>
public sealed class ContractFixesTests
{
    // ── Correctif 1 : JsonStringEnumConverter ──────────────────────────────

    [Fact]
    public void ValidateAlertRequest_DeserializesStringEnum_WithConverter()
    {
        // Reproduit fidèlement la configuration réelle d'ASP.NET Core, pas un
        // JsonSerializerOptions() nu — Microsoft.AspNetCore.Mvc.JsonOptions
        // active déjà PropertyNameCaseInsensitive=true par défaut (permet à
        // "action" de se lier à la propriété C# "Action"), en plus du
        // JsonStringEnumConverter ajouté explicitement dans Program.cs.
        // Un JsonSerializerOptions() nu aurait laissé passer ce test pour
        // une mauvaise raison — voir le commentaire du test négatif ci-dessous.
        var aspNetCoreDefaults = new Microsoft.AspNetCore.Mvc.JsonOptions();
        aspNetCoreDefaults.JsonSerializerOptions.Converters.Add(new JsonStringEnumConverter());

        var json = """{"action":"Confirm","note":"test"}""";

        var request = JsonSerializer.Deserialize<ValidateAlertRequest>(
            json, aspNetCoreDefaults.JsonSerializerOptions);

        Assert.NotNull(request);
        Assert.Equal(AlertValidationAction.Confirm, request!.Action);
        Assert.Equal("test", request.Note);
    }

    [Fact]
    public void ValidateAlertRequest_WithoutConverter_FailsToDeserializeStringEnum()
    {
        // Preuve négative isolée sur la VRAIE variable en jeu — le convertisseur
        // d'enum, pas la casse des propriétés. On garde l'insensibilité à la
        // casse (comportement ASP.NET Core réel) pour que "action" se lie
        // bien à la propriété Action ; seul le convertisseur d'enum est retiré.
        // Sans cet alignement, la liaison de propriété échouerait pour une
        // raison différente (mauvaise casse) et masquerait le vrai problème
        // qu'on veut prouver : sans convertisseur, un enum string lève
        // JsonException, il n'est jamais silencieusement ignoré.
        var optionsWithoutConverter = new Microsoft.AspNetCore.Mvc.JsonOptions()
            .JsonSerializerOptions;

        var json = """{"action":"Confirm","note":"test"}""";

        Assert.Throws<JsonException>(() =>
            JsonSerializer.Deserialize<ValidateAlertRequest>(json, optionsWithoutConverter));
    }

    // ── Correctif 2 : MapInboundClaims = false ─────────────────────────────

    [Fact]
    public async Task JwtHandler_WithMapInboundClaimsFalse_PreservesSubClaimLiterally()
    {
        const string signingKey = "test-signing-key-for-claim-mapping-verification-32c";
        const string issuer = "test-issuer";
        const string audience = "test-audience";
        const string expectedSub = "agent@bankily.mr";

        using var host = await new HostBuilder()
            .ConfigureWebHost(webBuilder =>
            {
                webBuilder.UseTestServer();
                webBuilder.ConfigureServices(services =>
                {
                    services.AddAuthentication()
                        .AddJwtAuthentication(new JwtAuthenticationOptions
                        {
                            Issuer = issuer,
                            Audience = audience,
                            SigningKey = signingKey
                        });
                    services.AddAuthorization();
                    services.AddRouting();
                });

                webBuilder.Configure(app =>
                {
                    app.UseRouting();
                    app.UseAuthentication();
                    app.UseAuthorization();
                    app.UseEndpoints(endpoints =>
                    {
                        endpoints.MapGet("/whoami", (HttpContext context) =>
                        {
                            var sub = context.User.FindFirst("sub")?.Value;
                            return Results.Ok(new { sub });
                        }).RequireAuthorization();
                    });
                });
            })
            .StartAsync();

        var client = host.GetTestClient();

        var token = BuildJwt(signingKey, issuer, audience, expectedSub);
        client.DefaultRequestHeaders.Authorization =
            new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", token);

        var response = await client.GetAsync("/whoami");
        var body = await response.Content.ReadAsStringAsync();

        Assert.Equal(System.Net.HttpStatusCode.OK, response.StatusCode);
        Assert.Contains(expectedSub, body);
    }

    private static string BuildJwt(
        string signingKey, string issuer, string audience, string subject)
    {
        var key = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(signingKey));
        var credentials = new SigningCredentials(key, SecurityAlgorithms.HmacSha256);

        var claims = new[] { new Claim("sub", subject) };

        var token = new JwtSecurityToken(
            issuer: issuer,
            audience: audience,
            claims: claims,
            expires: DateTime.UtcNow.AddMinutes(5),
            signingCredentials: credentials);

        return new JwtSecurityTokenHandler().WriteToken(token);
    }
}