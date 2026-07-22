using System.Net.Http.Json;
using FraudDetection.Application.Interfaces;
using FraudDetection.Domain.Entities;
using FraudDetection.Domain.Enums;
using FraudDetection.Domain.ValueObjects;
using FraudDetection.Infrastructure.ExternalServices.Dto;
using Microsoft.Extensions.Logging;
using Polly.CircuitBreaker;

namespace FraudDetection.Infrastructure.ExternalServices;

/// <summary>
/// Implémentation de IMlScoringService — client HTTP typé vers fraud-ml-service (FastAPI).
///
/// RÉSILIENCE : la politique Polly (retry + circuit breaker) est configurée
/// au niveau du HttpClient dans Program.cs (AddHttpClient + AddPolicyHandler),
/// pas dans cette classe. Ce service ne fait qu'appeler le HttpClient injecté —
/// Polly intercepte de façon transparente.
///
/// FALLBACK : toute exception (timeout, circuit ouvert, erreur réseau, erreur
/// de désérialisation) est interceptée ici et transformée en
/// RiskScore.DefaultReview() — cette classe ne laisse JAMAIS une exception
/// remonter au Handler Application. C'est le contrat documenté dans
/// IMlScoringService : "ne lève jamais d'exception sur une panne FastAPI".
///
/// CONTRAT FIGÉ : le mapping Transaction → TransactionInDto et
/// ScoreOutDto → RiskScore doit rester strictement fidèle à
/// presentation/schemas.py côté Python. Voir FastApiContractTests.cs.
/// </summary>
public sealed class MlScoringService : IMlScoringService
{
    private const string AnalyzeEndpoint = "/analyze";
    private const string HealthEndpoint = "/health";

    private readonly HttpClient _httpClient;
    private readonly ILogger<MlScoringService> _logger;

    public MlScoringService(HttpClient httpClient, ILogger<MlScoringService> logger)
    {
        _httpClient = httpClient;
        _logger = logger;
    }

    public async Task<RiskScore> AnalyzeAsync(
        Transaction transaction,
        CancellationToken cancellationToken = default)
    {
        try
        {
            var requestDto = MapToTransactionInDto(transaction);

            using var response = await _httpClient.PostAsJsonAsync(
                AnalyzeEndpoint, requestDto, cancellationToken);

            response.EnsureSuccessStatusCode();

            var responseDto = await response.Content.ReadFromJsonAsync<ScoreOutDto>(
                cancellationToken: cancellationToken);

            if (responseDto is null)
            {
                _logger.LogError(
                    "Réponse vide de fraud-ml-service pour TransactionId={TransactionId}. " +
                    "Application du fallback REVIEW.",
                    transaction.TransactionId);

                return RiskScore.DefaultReview();
            }

            return MapToRiskScore(responseDto);
        }
        catch (BrokenCircuitException ex)
        {
            // Le circuit breaker Polly a ouvert le circuit — FastAPI est considéré
            // en panne prolongée, on ne tente même pas l'appel réseau.
            _logger.LogWarning(ex,
                "Circuit breaker ouvert pour fraud-ml-service — " +
                "TransactionId={TransactionId}. Fallback REVIEW appliqué sans appel réseau.",
                transaction.TransactionId);

            return RiskScore.DefaultReview();
        }
        catch (HttpRequestException ex)
        {
            _logger.LogError(ex,
                "Échec réseau vers fraud-ml-service pour TransactionId={TransactionId}. " +
                "Fallback REVIEW appliqué.",
                transaction.TransactionId);

            return RiskScore.DefaultReview();
        }
        catch (TaskCanceledException ex) when (!cancellationToken.IsCancellationRequested)
        {
            // Timeout Polly (pas une annulation explicite du caller)
            _logger.LogError(ex,
                "Timeout vers fraud-ml-service pour TransactionId={TransactionId}. " +
                "Fallback REVIEW appliqué.",
                transaction.TransactionId);

            return RiskScore.DefaultReview();
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            // Filet de sécurité — toute autre exception inattendue (désérialisation
            // JSON malformée, mapping incohérent, etc.) ne doit jamais bloquer
            // le pipeline de détection. On log en Error car c'est potentiellement
            // un bug de contrat à investiguer, mais on continue en REVIEW.
            _logger.LogError(ex,
                "Erreur inattendue lors de l'analyse ML pour TransactionId={TransactionId}. " +
                "Fallback REVIEW appliqué. À investiguer — possible dérive de contrat.",
                transaction.TransactionId);

            return RiskScore.DefaultReview();
        }
    }

    public async Task<bool> IsHealthyAsync(CancellationToken cancellationToken = default)
    {
        try
        {
            using var response = await _httpClient.GetAsync(HealthEndpoint, cancellationToken);
            return response.IsSuccessStatusCode;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            _logger.LogDebug(ex, "Health check fraud-ml-service échoué.");
            return false;
        }
    }

    // ── Mapping Transaction (domaine) → TransactionInDto ─────────────────────

    private static TransactionInDto MapToTransactionInDto(Transaction transaction) =>
        new()
        {
            TransactionId = transaction.TransactionId,
            ClientToken = transaction.ClientToken.Value,
            Amount = transaction.Amount.Amount,
            Currency = transaction.Amount.Currency,
            Channel = MapChannel(transaction.Channel),
            Zone = transaction.Zone,
            Operator = transaction.Operator,
            DeviceId = transaction.DeviceId.Value,
            SimChanged72h = transaction.SimChanged72h,
            SimChangedAt = transaction.SimChangedAt?.ToString("yyyy-MM-ddTHH:mm:ssZ"),
            BeneficiaryToken = transaction.BeneficiaryToken.Value,
            BeneficiaryIsMerchant = transaction.BeneficiaryIsMerchant,
            AgentId = transaction.AgentId,
            UssdSession = transaction.UssdSession,
            Timestamp = transaction.Timestamp.ToString("yyyy-MM-ddTHH:mm:ssZ"),
            PreComputedFeatures = null
        };

    private static string MapChannel(Channel channel) => channel switch
    {
        Channel.MobileApp => "MOBILE_APP",
        Channel.Ussd => "USSD",
        Channel.Agent => "AGENT",
        Channel.Merchant => "MERCHANT",
        Channel.Atm => "ATM",
        _ => throw new ArgumentOutOfRangeException(
            nameof(channel), channel, "Canal non reconnu par le contrat FastAPI.")
    };

    // ── Mapping ScoreOutDto → RiskScore (domaine) ─────────────────────────────

    private static RiskScore MapToRiskScore(ScoreOutDto dto) =>
        new(
            score: dto.Score,
            decision: MapDecision(dto.Decision),
            fraudType: dto.FraudType,
            alertId: dto.AlertId,
            xgboostScore: dto.XgboostScore,
            isolationScore: dto.IsolationScore,
            tftScore: dto.TftScore,
            gnnScore: dto.GnnScore,
            inferenceTimeMs: dto.InferenceTimeMs,
            modelVersion: dto.ModelVersion);

    /// <summary>
    /// Traduit strictement la string Python vers l'enum .NET —
    /// ne recalcule jamais la décision. Une valeur inconnue lève
    /// une exception explicite plutôt qu'un fallback silencieux,
    /// car elle indiquerait une dérive de contrat non détectée
    /// par FastApiContractTests.cs.
    /// </summary>
    private static DecisionStatus MapDecision(string decision) => decision switch
    {
        "APPROVE" => DecisionStatus.Approve,
        "REVIEW" => DecisionStatus.Review,
        "BLOCK" => DecisionStatus.Block,
        _ => throw new InvalidOperationException(
            $"Décision inconnue reçue de fraud-ml-service : '{decision}'. " +
            $"Le contrat Python a peut-être changé — vérifier presentation/schemas.py " +
            $"et mettre à jour FastApiContractTests.cs.")
    };
}