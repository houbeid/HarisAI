using FraudDetection.Application.Interfaces;
using Microsoft.Extensions.Diagnostics.HealthChecks;

namespace FraudDetection.Infrastructure.Observability;

/// <summary>
/// Healthcheck "ready" — vérifie que fraud-ml-service répond.
/// Enregistré avec le tag "ready", jamais "live" : un pod dont FastAPI
/// est indisponible ne doit pas être redémarré (ce n'est pas le pod qui
/// est cassé), juste sorti temporairement de la rotation du Service K8s
/// jusqu'à ce que /health/ready redevienne positif.
///
/// Statut Degraded, pas Unhealthy : le service .NET reste fonctionnel
/// (REVIEW par défaut via Polly), donc "dégradé" reflète mieux la réalité
/// qu'un statut qui impliquerait un arrêt complet du service.
/// </summary>
public sealed class FraudMlServiceHealthCheck : IHealthCheck
{
    private readonly IMlScoringService _mlScoringService;

    public FraudMlServiceHealthCheck(IMlScoringService mlScoringService)
    {
        _mlScoringService = mlScoringService;
    }

    public async Task<HealthCheckResult> CheckHealthAsync(
        HealthCheckContext context,
        CancellationToken cancellationToken = default)
    {
        var isHealthy = await _mlScoringService.IsHealthyAsync(cancellationToken);

        return isHealthy
            ? HealthCheckResult.Healthy("fraud-ml-service répond normalement.")
            : HealthCheckResult.Degraded(
                "fraud-ml-service ne répond pas — REVIEW par défaut appliqué " +
                "aux nouvelles transactions (voir MlScoringService fallback Polly).");
    }
}