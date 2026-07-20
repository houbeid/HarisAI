namespace FraudDetection.Domain.ValueObjects;

/// <summary>
/// Représente un identifiant anonymisé — token client, device ID, ou token bénéficiaire.
/// JAMAIS une donnée personnelle brute (pas de numéro de téléphone, pas de nom).
///
/// Cohérent avec la contrainte Python : client_token et device_id sont des hashes
/// anonymisés envoyés à FastAPI — la PII n'atteint jamais le service ML.
/// L'anonymisation se fait en amont, dans l'adaptateur opérateur (BankilyWebhookAdapter),
/// avant que la Transaction du domaine ne soit construite.
/// </summary>
public sealed record TokenHash
{
    public string Value { get; }

    public TokenHash(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
            throw new ArgumentException("Le token ne peut pas être vide.", nameof(value));

        // Un hash cryptographique a toujours au minimum 8 caractères.
        // Cette garde évite qu'un numéro de téléphone brut soit passé par erreur.
        if (value.Trim().Length < 8)
            throw new ArgumentException(
                "Token trop court — un hash valide fait au minimum 8 caractères. " +
                "Vérifier que l'anonymisation a bien été appliquée avant la construction du domaine.",
                nameof(value));

        Value = value.Trim();
    }

    public override string ToString() => Value;

    /// <summary>
    /// Vérifie que deux tokens représentent le même compte (comparaison de hash).
    /// Utilisé notamment pour détecter si client == bénéficiaire (transfert à soi-même).
    /// </summary>
    public bool IsSameAs(TokenHash other) =>
        string.Equals(Value, other.Value, StringComparison.OrdinalIgnoreCase);
}