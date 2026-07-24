using System.Security.Cryptography;
using System.Text;
using FraudDetection.Infrastructure.Auth;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Xunit;

namespace FraudDetection.Tests.Infrastructure.Auth;

/// <summary>
/// Tests d'intégration de HmacAuthenticationHandler via un vrai pipeline HTTP
/// (TestServer) — nécessaire car HandleAuthenticateAsync est protected et
/// dépend de tout le contexte ASP.NET Core (HttpContext, Options, Scheme).
/// Reproduit fidèlement ce qu'un vrai webhook opérateur enverrait.
/// </summary>
public sealed class HmacAuthenticationHandlerTests : IAsyncLifetime
{
    private const string TestSecret = "test-secret-for-hmac-validation-32chars";
    private const string TestOperator = "BANKILY";

    private IHost _host = null!;
    private HttpClient _client = null!;

    public async Task InitializeAsync()
    {
        _host = await new HostBuilder()
            .ConfigureWebHost(webBuilder =>
            {
                webBuilder.UseTestServer();
                webBuilder.ConfigureServices(services =>
                {
                    services.AddSingleton<IConfiguration>(
                        new ConfigurationBuilder()
                            .AddInMemoryCollection(new Dictionary<string, string?>
                            {
                                [$"OperatorSecrets:{TestOperator}"] = TestSecret
                            })
                            .Build());

                    services.AddSingleton<IOperatorSecretProvider, OperatorSecretProvider>();

                    services.AddAuthentication()
                        .AddScheme<HmacAuthenticationOptions, HmacAuthenticationHandler>(
                            "Hmac", options =>
                            {
                                options.ReplayWindow = TimeSpan.FromMinutes(5);
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
                        endpoints.MapPost("/webhook", async context =>
                        {
                            var result = await context.AuthenticateAsync("Hmac");
                            if (!result.Succeeded)
                            {
                                context.Response.StatusCode = 401;
                                return;
                            }

                            var operatorCode = result.Principal!.FindFirst("operator_code")?.Value;
                            context.Response.StatusCode = 200;
                            await context.Response.WriteAsync(operatorCode ?? "");
                        });
                    });
                });
            })
            .StartAsync();

        _client = _host.GetTestClient();
    }

    public async Task DisposeAsync()
    {
        _client.Dispose();
        await _host.StopAsync();
        _host.Dispose();
    }

    /// <summary>Reproduit exactement le calcul de signature attendu côté opérateur.</summary>
    private static string ComputeSignature(long timestamp, string body, string secret)
    {
        var payload = $"{timestamp}.{body}";
        using var hmac = new HMACSHA256(Encoding.UTF8.GetBytes(secret));
        var hash = hmac.ComputeHash(Encoding.UTF8.GetBytes(payload));
        return Convert.ToHexString(hash).ToLowerInvariant();
    }

    private HttpRequestMessage BuildRequest(
        string body,
        string? operatorCode = TestOperator,
        string? signature = null,
        long? timestamp = null,
        string secret = TestSecret,
        bool includeSha256Prefix = false)
    {
        var ts = timestamp ?? DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        var sig = signature ?? ComputeSignature(ts, body, secret);

        var request = new HttpRequestMessage(HttpMethod.Post, "/webhook")
        {
            Content = new StringContent(body, Encoding.UTF8, "application/json")
        };

        if (operatorCode is not null)
            request.Headers.Add("X-Operator-Code", operatorCode);

        request.Headers.Add("X-Signature", includeSha256Prefix ? $"sha256={sig}" : sig);
        request.Headers.Add("X-Timestamp", ts.ToString());

        return request;
    }

    // ── Cas valides ───────────────────────────────────────────────────────────

    [Fact]
    public async Task Authenticate_ValidSignature_Returns200WithOperatorCode()
    {
        var request = BuildRequest("""{"transaction_id":"BNK-001"}""");

        var response = await _client.SendAsync(request);
        var body = await response.Content.ReadAsStringAsync();

        Assert.Equal(System.Net.HttpStatusCode.OK, response.StatusCode);
        Assert.Equal(TestOperator, body);
    }

    [Fact]
    public async Task Authenticate_SignatureWithSha256Prefix_Returns200()
    {
        var request = BuildRequest(
            """{"transaction_id":"BNK-001"}""", includeSha256Prefix: true);

        var response = await _client.SendAsync(request);

        Assert.Equal(System.Net.HttpStatusCode.OK, response.StatusCode);
    }

    // ── Headers manquants ────────────────────────────────────────────────────

    [Fact]
    public async Task Authenticate_MissingOperatorHeader_Returns401()
    {
        var request = BuildRequest("""{"a":1}""", operatorCode: null);

        var response = await _client.SendAsync(request);

        Assert.Equal(System.Net.HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task Authenticate_MissingSignatureHeader_Returns401()
    {
        var ts = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        var request = new HttpRequestMessage(HttpMethod.Post, "/webhook")
        {
            Content = new StringContent("""{"a":1}""", Encoding.UTF8, "application/json")
        };
        request.Headers.Add("X-Operator-Code", TestOperator);
        request.Headers.Add("X-Timestamp", ts.ToString());
        // Pas de X-Signature

        var response = await _client.SendAsync(request);

        Assert.Equal(System.Net.HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task Authenticate_InvalidTimestampFormat_Returns401()
    {
        var request = new HttpRequestMessage(HttpMethod.Post, "/webhook")
        {
            Content = new StringContent("""{"a":1}""", Encoding.UTF8, "application/json")
        };
        request.Headers.Add("X-Operator-Code", TestOperator);
        request.Headers.Add("X-Signature", "abc123");
        request.Headers.Add("X-Timestamp", "not-a-number");

        var response = await _client.SendAsync(request);

        Assert.Equal(System.Net.HttpStatusCode.Unauthorized, response.StatusCode);
    }

    // ── Signature invalide ───────────────────────────────────────────────────

    [Fact]
    public async Task Authenticate_WrongSignature_Returns401()
    {
        var request = BuildRequest(
            """{"transaction_id":"BNK-001"}""",
            signature: "0000000000000000000000000000000000000000000000000000000000000000");

        var response = await _client.SendAsync(request);

        Assert.Equal(System.Net.HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task Authenticate_SignedWithWrongSecret_Returns401()
    {
        var request = BuildRequest(
            """{"transaction_id":"BNK-001"}""",
            secret: "wrong-secret-completely-different-32c");

        var response = await _client.SendAsync(request);

        Assert.Equal(System.Net.HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task Authenticate_TamperedBody_Returns401()
    {
        // Signature calculée sur un corps différent de celui réellement envoyé —
        // simule une interception + modification en transit.
        var ts = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        var signatureForOriginalBody = ComputeSignature(
            ts, """{"amount":1000}""", TestSecret);

        var request = new HttpRequestMessage(HttpMethod.Post, "/webhook")
        {
            Content = new StringContent(
                """{"amount":999999}""", Encoding.UTF8, "application/json")
        };
        request.Headers.Add("X-Operator-Code", TestOperator);
        request.Headers.Add("X-Signature", signatureForOriginalBody);
        request.Headers.Add("X-Timestamp", ts.ToString());

        var response = await _client.SendAsync(request);

        Assert.Equal(System.Net.HttpStatusCode.Unauthorized, response.StatusCode);
    }

    // ── Anti-replay ───────────────────────────────────────────────────────────

    [Fact]
    public async Task Authenticate_TimestampTooOld_Returns401()
    {
        var oldTimestamp = DateTimeOffset.UtcNow.AddMinutes(-10).ToUnixTimeSeconds();
        var request = BuildRequest(
            """{"a":1}""", timestamp: oldTimestamp);

        var response = await _client.SendAsync(request);

        Assert.Equal(System.Net.HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task Authenticate_TimestampInFuture_Returns401()
    {
        // Un timestamp dans le futur ne devrait jamais être accepté —
        // signe soit une horloge désynchronisée, soit une tentative suspecte.
        var futureTimestamp = DateTimeOffset.UtcNow.AddMinutes(10).ToUnixTimeSeconds();
        var request = BuildRequest(
            """{"a":1}""", timestamp: futureTimestamp);

        var response = await _client.SendAsync(request);

        Assert.Equal(System.Net.HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task Authenticate_TimestampWithinWindow_Returns200()
    {
        var recentTimestamp = DateTimeOffset.UtcNow.AddMinutes(-2).ToUnixTimeSeconds();
        var request = BuildRequest(
            """{"a":1}""", timestamp: recentTimestamp);

        var response = await _client.SendAsync(request);

        Assert.Equal(System.Net.HttpStatusCode.OK, response.StatusCode);
    }

    // ── Opérateur inconnu ────────────────────────────────────────────────────

    [Fact]
    public async Task Authenticate_UnknownOperator_Returns401()
    {
        var ts = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        var body = """{"a":1}""";
        // Signature calculée avec un secret arbitraire — peu importe,
        // aucun secret n'est configuré pour "SEDAD" dans ce test.
        var signature = ComputeSignature(ts, body, "un-secret-quelconque");

        var request = new HttpRequestMessage(HttpMethod.Post, "/webhook")
        {
            Content = new StringContent(body, Encoding.UTF8, "application/json")
        };
        request.Headers.Add("X-Operator-Code", "SEDAD");
        request.Headers.Add("X-Signature", signature);
        request.Headers.Add("X-Timestamp", ts.ToString());

        var response = await _client.SendAsync(request);

        Assert.Equal(System.Net.HttpStatusCode.Unauthorized, response.StatusCode);
    }
}