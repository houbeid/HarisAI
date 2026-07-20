using FraudDetection.Domain.ValueObjects;

namespace FraudDetection.Domain.Entities;

/// <summary>
/// Profil comportemental agrégé d'un client, stocké dans Redis côté Python
/// (RedisProfileStore) et retourné à .NET pour enrichir le contexte de la transaction.
///
/// IMPORTANT : côté Python, ClientProfile est la source de vérité et est mis à jour
/// en continu. Côté .NET, c'est un miroir en LECTURE SEULE — .NET ne met jamais
/// à jour ce profil directement. La logique métier (is_dormant_account, etc.)
/// reste exclusivement côté Python.
/// </summary>
public sealed class ClientProfile
{
    public TokenHash ClientToken { get; }
    public string Operator { get; }
    public decimal AvgAmount7d { get; }
    public decimal AvgAmount30d { get; }
    public int TotalTransactions { get; }
    public int AccountAgeDays { get; }
    public DateTime? LastTransactionAt { get; }
    public bool IsNewAccount { get; }
    public bool IsDormantAccount { get; }

    public ClientProfile(
        TokenHash clientToken,
        string @operator,
        decimal avgAmount7d,
        decimal avgAmount30d,
        int totalTransactions,
        int accountAgeDays,
        DateTime? lastTransactionAt,
        bool isNewAccount,
        bool isDormantAccount)
    {
        if (string.IsNullOrWhiteSpace(@operator))
            throw new ArgumentException("Operator ne peut pas être vide.", nameof(@operator));

        if (avgAmount7d < 0)
            throw new ArgumentException("AvgAmount7d ne peut pas être négatif.", nameof(avgAmount7d));

        if (avgAmount30d < 0)
            throw new ArgumentException("AvgAmount30d ne peut pas être négatif.", nameof(avgAmount30d));

        if (totalTransactions < 0)
            throw new ArgumentException("TotalTransactions ne peut pas être négatif.", nameof(totalTransactions));

        if (accountAgeDays < 0)
            throw new ArgumentException("AccountAgeDays ne peut pas être négatif.", nameof(accountAgeDays));

        ClientToken = clientToken;
        Operator = @operator.Trim().ToUpperInvariant();
        AvgAmount7d = avgAmount7d;
        AvgAmount30d = avgAmount30d;
        TotalTransactions = totalTransactions;
        AccountAgeDays = accountAgeDays;
        LastTransactionAt = lastTransactionAt;
        IsNewAccount = isNewAccount;
        IsDormantAccount = isDormantAccount;
    }

    /// <summary>
    /// Profil vide pour un client inconnu — premier contact avec le système.
    /// Utilisé quand Redis ne retourne aucun profil existant pour ce token.
    /// </summary>
    public static ClientProfile Empty(TokenHash clientToken, string @operator) =>
        new(
            clientToken: clientToken,
            @operator: @operator,
            avgAmount7d: 0,
            avgAmount30d: 0,
            totalTransactions: 0,
            accountAgeDays: 0,
            lastTransactionAt: null,
            isNewAccount: true,
            isDormantAccount: false);

    public override string ToString() =>
        $"[{Operator}] Token={ClientToken} Txs={TotalTransactions} AgeDays={AccountAgeDays}";
}