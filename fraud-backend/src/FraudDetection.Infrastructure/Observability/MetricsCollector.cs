using Prometheus;

namespace FraudDetection.Infrastructure.Observability;

/// <summary>
/// Implémentation de IMetricsCollector avec prometheus-net.
/// Utilise le CollectorRegistry par défaut de la librairie — exposé
/// automatiquement sur /metrics une fois app.MapMetrics() appelé dans
/// Program.cs (voir prometheus-net.AspNetCore).
///
/// PRÉFIXE "fraudbackend_" SUR TOUTES LES MÉTRIQUES : garantit zéro
/// collision avec les 13 métriques déjà exposées côté Python
/// (transactions_total, decisions_total, etc. — sans préfixe, définies
/// dans infrastructure/monitoring/metrics.py). Prometheus scrape les deux
/// services séparément (voir prometheus.yml — deux scrape targets), donc
/// techniquement les métriques identiques ne s'écraseraient pas au scrape,
/// mais des noms identiques avec des sémantiques différentes entre les deux
/// services prêteraient à confusion dans Grafana. Le préfixe lève toute
/// ambiguïté visuellement.
/// </summary>
public sealed class MetricsCollector : IMetricsCollector
{
    private static readonly Counter MlCallsTotal = Metrics.CreateCounter(
        "fraudbackend_ml_calls_total",
        "Nombre total d'appels à fraud-ml-service, par résultat.",
        new CounterConfiguration
        {
            LabelNames = new[] { "outcome" } // "success" | "fallback"
        });

    private static readonly Histogram MlCallDurationSeconds = Metrics.CreateHistogram(
        "fraudbackend_ml_call_duration_seconds",
        "Durée des appels à fraud-ml-service, y compris les appels en échec " +
        "ayant déclenché le fallback Polly.");

    private static readonly Gauge PendingQueueSize = Metrics.CreateGauge(
        "fraudbackend_pending_queue_size",
        "Nombre de transactions en attente de rescoring dans la file de résilience.",
        new GaugeConfiguration
        {
            LabelNames = new[] { "operator" }
        });

    private static readonly Gauge AlertsPendingCount = Metrics.CreateGauge(
        "fraudbackend_alerts_pending_count",
        "Nombre d'alertes en statut Pending, en attente de traitement par un agent.",
        new GaugeConfiguration
        {
            LabelNames = new[] { "operator" }
        });

    public void RecordMlCall(bool isDefaultReview, double durationMs)
    {
        var outcome = isDefaultReview ? "fallback" : "success";
        MlCallsTotal.WithLabels(outcome).Inc();
        MlCallDurationSeconds.Observe(durationMs / 1000.0);
    }

    public void SetPendingQueueSize(string operatorCode, int size)
    {
        PendingQueueSize.WithLabels(operatorCode).Set(size);
    }

    public void SetAlertsPendingCount(string operatorCode, int count)
    {
        AlertsPendingCount.WithLabels(operatorCode).Set(count);
    }
}