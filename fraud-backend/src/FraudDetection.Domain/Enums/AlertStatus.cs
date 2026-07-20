namespace FraudDetection.Domain.Enums;

/// <summary>
/// Cycle de vie d'une alerte générée pour une transaction REVIEW ou BLOCK.
/// Un agent de conformité humain traite les alertes Pending depuis fraud-dashboard.
/// </summary>
public enum AlertStatus
{
    /// <summary>Alerte créée, en attente de traitement par un agent de conformité</summary>
    Pending,

    /// <summary>Agent a confirmé qu'il s'agit d'une vraie fraude — STR BCM déclenché</summary>
    Confirmed,

    /// <summary>Agent a écarté l'alerte — faux positif</summary>
    Dismissed
}