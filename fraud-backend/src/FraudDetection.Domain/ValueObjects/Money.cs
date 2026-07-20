namespace FraudDetection.Domain.ValueObjects;

/// <summary>
/// Représente un montant monétaire en Ouguiya mauritanien (MRU).
/// Immutable — une fois créé, ne peut pas être modifié.
///
/// Contrainte actuelle : seule la devise MRU est supportée.
/// Si un autre pays africain est intégré, cette contrainte sera levée
/// en coordination avec la mise à jour de la liste blanche côté FastAPI.
/// </summary>
public sealed record Money
{
    public decimal Amount { get; }
    public string Currency { get; }

    public Money(decimal amount, string currency)
    {
        if (amount <= 0)
            throw new ArgumentException(
                $"Le montant doit être strictement positif. Valeur reçue : {amount}",
                nameof(amount));

        if (string.IsNullOrWhiteSpace(currency))
            throw new ArgumentException("La devise ne peut pas être vide.", nameof(currency));

        // Seule devise supportée actuellement — cohérent avec la validation Python
        // (TransactionIn valide currency == "MRU"). À étendre lors de l'intégration
        // d'un premier opérateur hors Mauritanie.
        if (currency.ToUpperInvariant() != "MRU")
            throw new ArgumentException(
                $"Devise non supportée : {currency}. Seule MRU est acceptée actuellement.",
                nameof(currency));

        Amount = amount;
        Currency = currency.ToUpperInvariant();
    }

    public override string ToString() => $"{Amount} {Currency}";
}