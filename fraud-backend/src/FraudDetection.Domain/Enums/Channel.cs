namespace FraudDetection.Domain.Enums;

/// <summary>
/// Canaux de transaction mobile money mauritanien.
/// Reflète la réalité du marché local — pas un modèle occidental générique.
/// Miroir du Channel Python (domain/enums.py).
///
/// Ces valeurs sont validées par FastAPI côté Python avant tout scoring —
/// .NET doit les valider aussi avant d'envoyer TransactionIn.
/// </summary>
public enum Channel
{
    /// <summary>Application Bankily ou Sedad — canal standard smartphones</summary>
    MobileApp,

    /// <summary>*888# — canal dominant pour les téléphones basiques, très répandu en Mauritanie</summary>
    Ussd,

    /// <summary>Agent physique terrain — dépôts et retraits en espèces</summary>
    Agent,

    /// <summary>Paiement chez un marchand affilié</summary>
    Merchant,

    /// <summary>Retrait guichet automatique</summary>
    Atm
}