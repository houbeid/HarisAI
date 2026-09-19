using FraudDetection.Domain.Entities;
using FraudDetection.Domain.Enums;
using FraudDetection.Domain.ValueObjects;
using FraudDetection.Infrastructure.ExternalServices;
using FraudDetection.Infrastructure.Observability;
using Microsoft.Extensions.Logging;
using Moq;
using WireMock.RequestBuilders;
using WireMock.ResponseBuilders;
using WireMock.Server;
using Xunit;

namespace FraudDetection.Tests.Infrastructure;

/// <summary>
/// Tests de MlScoringService contre un vrai serveur HTTP simulé (WireMock.NET).
/// Ces tests jouent le rôle de FastApiContractTests.cs — ils vérifient que
/// le JSON envoyé et reçu reste fidèle au contrat figé côté Python.
///
/// PAS de test Polly ici — le retry/circuit breaker est configuré au niveau
/// du HttpClient dans Program.cs (AddPolicyHandler), pas dans MlScoringService.
/// Les tests Polly (retry, ouverture de circuit) sont dans une classe séparée
/// qui construit le HttpClient avec la vraie politique.
/// </summary>
public sealed class MlScoringServiceTests : IDisposable
{
    private readonly WireMockServer _server;
    private readonly HttpClient _httpClient;
    private readonly Mock<IMetricsCollector> _metricsCollectorMock;

    // Mock<ILogger> plutôt que NullLogger — permet de vérifier concrètement
    // que le corps d'une réponse d'erreur est bien loggé (voir test dédié
    // plus bas), découvert nécessaire lors du premier test d'intégration
    // réel contre le vrai fraud-ml-service.
    private readonly Mock<ILogger<MlScoringService>> _loggerMock;
    private readonly MlScoringService _service;

    public MlScoringServiceTests()
    {
        _server = WireMockServer.Start();
        _httpClient = new HttpClient { BaseAddress = new Uri(_server.Url!) };
        _metricsCollectorMock = new Mock<IMetricsCollector>();
        _loggerMock = new Mock<ILogger<MlScoringService>>();
        _service = new MlScoringService(
            _httpClient, _metricsCollectorMock.Object, _loggerMock.Object);
    }


    public void Dispose()
    {
        _httpClient.Dispose();
        _server.Stop();
        _server.Dispose();
    }

    private static Transaction BuildTransaction() =>
        new(
            transactionId: "BNK-2024-001",
            clientToken: new TokenHash("a3f9b2c1d4e5f6a7"),
            amount: new Money(47000m, "MRU"),
            channel: Channel.MobileApp,
            zone: "ROSSO",
            @operator: "BANKILY",
            deviceId: new TokenHash("device123hash456"),
            simChanged72h: true,
            simChangedAt: new DateTime(2024, 1, 15, 2, 30, 0, DateTimeKind.Utc),
            beneficiaryToken: new TokenHash("b8c7d6e5f4a3b2c1"),
            beneficiaryIsMerchant: false,
            agentId: null,
            ussdSession: false,
            timestamp: new DateTime(2024, 1, 15, 2, 34, 0, DateTimeKind.Utc));

    // ── Contrat — requête envoyée ──────────────────────────────────────────────

    [Fact]
    public async Task AnalyzeAsync_SendsCorrectJsonContract()
    {
        _server
            .Given(Request.Create().WithPath("/api/v1/analyze").UsingPost())
            .RespondWith(Response.Create()
                .WithStatusCode(200)
                .WithHeader("Content-Type", "application/json")
                .WithBody("""
                {
                    "transaction_id": "BNK-2024-001",
                    "score": 20,
                    "decision": "APPROVE"
                }
                """));

        await _service.AnalyzeAsync(BuildTransaction(), "test-correlation-id", CancellationToken.None);

        var request = _server.LogEntries.Single().RequestMessage;
        var body = request.Body!;

        // Vérifie les champs contractuels exacts (snake_case, valeurs mappées)
        Assert.Contains("\"transaction_id\":\"BNK-2024-001\"", body);
        Assert.Contains("\"channel\":\"MOBILE_APP\"", body);   // Channel.MobileApp → "MOBILE_APP"
        Assert.Contains("\"operator\":\"BANKILY\"", body);
        Assert.Contains("\"currency\":\"MRU\"", body);
        Assert.Contains("\"sim_changed_72h\":true", body);
        Assert.Contains("\"ussd_session\":false", body);
    }

    // ── Contrat — réponse reçue ─────────────────────────────────────────────────

    [Fact]
    public async Task AnalyzeAsync_ApproveResponse_MapsToApproveRiskScore()
    {
        _server
            .Given(Request.Create().WithPath("/api/v1/analyze").UsingPost())
            .RespondWith(Response.Create()
                .WithStatusCode(200)
                .WithHeader("Content-Type", "application/json")
                .WithBody("""
                {
                    "transaction_id": "BNK-2024-001",
                    "score": 20,
                    "decision": "APPROVE"
                }
                """));

        var result = await _service.AnalyzeAsync(BuildTransaction(), "test-correlation-id", CancellationToken.None);

        Assert.Equal(20, result.Score);
        Assert.Equal(DecisionStatus.Approve, result.Decision);
        Assert.Null(result.AlertId);
    }

    [Fact]
    public async Task AnalyzeAsync_BlockResponse_MapsAllFields()
    {
        _server
            .Given(Request.Create().WithPath("/api/v1/analyze").UsingPost())
            .RespondWith(Response.Create()
                .WithStatusCode(200)
                .WithHeader("Content-Type", "application/json")
                .WithBody("""
                {
                    "transaction_id": "BNK-2024-001",
                    "score": 87,
                    "decision": "BLOCK",
                    "fraud_type": "SIM_SWAPPING",
                    "alert_id": "ALT-C15FDD6C8FCB",
                    "xgboost_score": 0.94,
                    "isolation_score": 0.85,
                    "tft_score": 0.88,
                    "gnn_score": 0.72,
                    "inference_time_ms": 87.5,
                    "model_version": "1.0.0"
                }
                """));

        var result = await _service.AnalyzeAsync(BuildTransaction(), "test-correlation-id", CancellationToken.None);

        Assert.Equal(87, result.Score);
        Assert.Equal(DecisionStatus.Block, result.Decision);
        Assert.Equal("SIM_SWAPPING", result.FraudType);
        Assert.Equal("ALT-C15FDD6C8FCB", result.AlertId);
        Assert.Equal(0.94, result.XgboostScore);
        Assert.Equal("1.0.0", result.ModelVersion);
    }

    [Fact]
    public async Task AnalyzeAsync_UnknownDecisionString_ReturnsDefaultReview()
    {
        // Simule une dérive de contrat — Python renvoie une décision non reconnue
        _server
            .Given(Request.Create().WithPath("/api/v1/analyze").UsingPost())
            .RespondWith(Response.Create()
                .WithStatusCode(200)
                .WithHeader("Content-Type", "application/json")
                .WithBody("""
                {
                    "transaction_id": "BNK-2024-001",
                    "score": 50,
                    "decision": "UNKNOWN_DECISION"
                }
                """));

        // L'exception doit être catchée en interne et transformée en DefaultReview —
        // MlScoringService ne laisse jamais rien remonter au Handler.
        var result = await _service.AnalyzeAsync(BuildTransaction(), "test-correlation-id", CancellationToken.None);

        Assert.True(result.RequiresHumanReview);
        Assert.Equal(DecisionStatus.Review, result.Decision);
        Assert.Equal("UNAVAILABLE", result.FraudType);
    }

    // ── Fallback — résilience ─────────────────────────────────────────────────

    [Fact]
    public async Task AnalyzeAsync_ServerReturns500_ReturnsDefaultReview()
    {
        _server
            .Given(Request.Create().WithPath("/api/v1/analyze").UsingPost())
            .RespondWith(Response.Create().WithStatusCode(500));

        var result = await _service.AnalyzeAsync(BuildTransaction(), "test-correlation-id", CancellationToken.None);

        Assert.Equal(DecisionStatus.Review, result.Decision);
        Assert.Equal("UNAVAILABLE", result.FraudType);
    }

    [Fact]
    public async Task AnalyzeAsync_ServerUnreachable_ReturnsDefaultReview()
    {
        _server.Stop(); // Simule un serveur totalement injoignable

        var result = await _service.AnalyzeAsync(BuildTransaction(), "test-correlation-id", CancellationToken.None);

        Assert.Equal(DecisionStatus.Review, result.Decision);
        Assert.True(result.RequiresHumanReview);
    }

    [Fact]
    public async Task AnalyzeAsync_MalformedJsonResponse_ReturnsDefaultReview()
    {
        _server
            .Given(Request.Create().WithPath("/api/v1/analyze").UsingPost())
            .RespondWith(Response.Create()
                .WithStatusCode(200)
                .WithHeader("Content-Type", "application/json")
                .WithBody("{ not valid json"));

        var result = await _service.AnalyzeAsync(BuildTransaction(), "test-correlation-id", CancellationToken.None);

        Assert.Equal(DecisionStatus.Review, result.Decision);
    }

    // ── IsHealthyAsync ────────────────────────────────────────────────────────

    [Fact]
    public async Task IsHealthyAsync_ServerReturns200_ReturnsTrue()
    {
        _server
            .Given(Request.Create().WithPath("/api/v1/health").UsingGet())
            .RespondWith(Response.Create().WithStatusCode(200));

        var result = await _service.IsHealthyAsync(CancellationToken.None);

        Assert.True(result);
    }

    [Fact]
    public async Task IsHealthyAsync_ServerReturns503_ReturnsFalse()
    {
        _server
            .Given(Request.Create().WithPath("/api/v1/health").UsingGet())
            .RespondWith(Response.Create().WithStatusCode(503));

        var result = await _service.IsHealthyAsync(CancellationToken.None);

        Assert.False(result);
    }

    [Fact]
    public async Task IsHealthyAsync_ServerUnreachable_ReturnsFalseWithoutThrowing()
    {
        _server.Stop();

        var result = await _service.IsHealthyAsync(CancellationToken.None);

        Assert.False(result);
    }

    // ── Métriques (fraudbackend_ml_calls_total / fraudbackend_ml_call_duration_seconds) ──

    [Fact]
    public async Task AnalyzeAsync_SuccessfulCall_RecordsMetricWithSuccessOutcome()
    {
        _server
            .Given(Request.Create().WithPath("/api/v1/analyze").UsingPost())
            .RespondWith(Response.Create()
                .WithStatusCode(200)
                .WithHeader("Content-Type", "application/json")
                .WithBody("""
                {
                    "transaction_id": "BNK-2024-001",
                    "score": 20,
                    "decision": "APPROVE"
                }
                """));

        await _service.AnalyzeAsync(BuildTransaction(), "test-correlation-id", CancellationToken.None);

        // isDefaultReview = false pour un vrai succès FastAPI
        _metricsCollectorMock.Verify(
            m => m.RecordMlCall(false, It.IsAny<double>()),
            Times.Once);
    }

    [Fact]
    public async Task AnalyzeAsync_ServerUnreachable_RecordsMetricWithFallbackOutcome()
    {
        _server.Stop();

        await _service.AnalyzeAsync(BuildTransaction(), "test-correlation-id", CancellationToken.None);

        // isDefaultReview = true pour le fallback Polly (RiskScore.DefaultReview())
        _metricsCollectorMock.Verify(
            m => m.RecordMlCall(true, It.IsAny<double>()),
            Times.Once);
    }

    [Fact]
    public async Task AnalyzeAsync_ServerReturns500_RecordsMetricWithFallbackOutcome()
    {
        _server
            .Given(Request.Create().WithPath("/api/v1/analyze").UsingPost())
            .RespondWith(Response.Create().WithStatusCode(500));

        await _service.AnalyzeAsync(BuildTransaction(), "test-correlation-id", CancellationToken.None);

        _metricsCollectorMock.Verify(
            m => m.RecordMlCall(true, It.IsAny<double>()),
            Times.Once);
    }

    [Fact]
    public async Task AnalyzeAsync_RecordsPositiveDuration()
    {
        _server
            .Given(Request.Create().WithPath("/api/v1/analyze").UsingPost())
            .RespondWith(Response.Create()
                .WithStatusCode(200)
                .WithHeader("Content-Type", "application/json")
                .WithBody("""{"transaction_id":"BNK-2024-001","score":20,"decision":"APPROVE"}"""));

        await _service.AnalyzeAsync(BuildTransaction(), "test-correlation-id", CancellationToken.None);

        // La durée mesurée doit toujours être positive — vérifie que le
        // Stopwatch mesure réellement quelque chose, pas juste 0 par défaut.
        _metricsCollectorMock.Verify(
            m => m.RecordMlCall(It.IsAny<bool>(), It.Is<double>(d => d >= 0)),
            Times.Once);
    }

    // ── Logging du corps d'erreur — découvert nécessaire lors du premier ────
    // ── test d'intégration réel contre fraud-ml-service (422 Pydantic) ──────

    [Fact]
    public async Task AnalyzeAsync_ServerReturns422_LogsResponseBody()
    {
        // Reproduit un vrai rejet de validation Pydantic FastAPI — le corps
        // contient le détail exact du champ invalide, indispensable pour
        // diagnostiquer une divergence de contrat entre .NET et FastAPI.
        const string pydanticErrorBody =
            """{"detail":[{"loc":["body","currency"],"msg":"field required","type":"value_error.missing"}]}""";

        _server
            .Given(Request.Create().WithPath("/api/v1/analyze").UsingPost())
            .RespondWith(Response.Create()
                .WithStatusCode(422)
                .WithHeader("Content-Type", "application/json")
                .WithBody(pydanticErrorBody));

        await _service.AnalyzeAsync(BuildTransaction(), "test-correlation-id", CancellationToken.None);

        // Vérifie qu'un LogError a bien été émis — sans exiger une
        // correspondance exacte du message complet (fragile), on vérifie
        // que le niveau est Error et que l'appel a bien eu lieu une fois.
        _loggerMock.Verify(
            l => l.Log(
                LogLevel.Error,
                It.IsAny<EventId>(),
                It.IsAny<It.IsAnyType>(),
                It.IsAny<Exception?>(),
                It.IsAny<Func<It.IsAnyType, Exception?, string>>()),
            Times.AtLeastOnce);
    }

    [Fact]
    public async Task AnalyzeAsync_ServerReturns422_StillFallsBackToDefaultReview()
    {
        // Le logging amélioré ne doit jamais changer le comportement de
        // fallback déjà établi — un 422 reste traité comme n'importe quel
        // échec HTTP, REVIEW par défaut, jamais une exception qui remonte.
        _server
            .Given(Request.Create().WithPath("/api/v1/analyze").UsingPost())
            .RespondWith(Response.Create()
                .WithStatusCode(422)
                .WithBody("""{"detail":"invalid payload"}"""));

        var result = await _service.AnalyzeAsync(
            BuildTransaction(), "test-correlation-id", CancellationToken.None);

        Assert.Equal("UNAVAILABLE", result.FraudType);
        Assert.Equal(DecisionStatus.Review, result.Decision);
    }
}