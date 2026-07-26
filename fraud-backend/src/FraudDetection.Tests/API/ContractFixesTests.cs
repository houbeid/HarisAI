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
        // Reproduit exactement la configuration ajoutée dans Program.cs —
        // si ce test passe, le frontend peut envoyer {"action":"Confirm"}
        // sans échec de désérialisation.
        var options = new JsonSerializerOptions();
        options.Converters.Add(new JsonStringEnumConverter());

        var json = """{"action":"Confirm","note":"test"}""";

        var request = JsonSerializer.Deserialize<ValidateAlertRequest>(json, options);

        Assert.NotNull(request);
        Assert.Equal(AlertValidationAction.Confirm, request!.Action);
        Assert.Equal("test", request.Note);
    }

    [Fact]
    public void ValidateAlertRequest_WithoutConverter_FailsToDeserializeStringEnum()
    {
        // Preuve négative — sans le convertisseur, la même chaîne JSON échoue.
        // Documente concrètement le bug qui existait avant le correctif.
        var optionsWithoutConverter = new JsonSerializerOptions();
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