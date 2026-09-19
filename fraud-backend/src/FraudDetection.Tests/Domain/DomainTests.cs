using FraudDetection.Domain.Entities;
using FraudDetection.Domain.Enums;
using FraudDetection.Domain.Events;
using FraudDetection.Domain.ValueObjects;
using Xunit;

namespace FraudDetection.Tests.Domain;

// ═══════════════════════════════════════════════════════════
// MONEY
// ═══════════════════════════════════════════════════════════

public class MoneyTests
{
    [Fact]
    public void Money_ValidAmount_CreatesSuccessfully()
    {
        var money = new Money(47000m, "MRU");
        Assert.Equal(47000m, money.Amount);
        Assert.Equal("MRU", money.Currency);
    }

    [Fact]
    public void Money_NormalizesLowercaseCurrency()
    {
        var money = new Money(1000m, "mru");
        Assert.Equal("MRU", money.Currency);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(-1)]
    [InlineData(-100)]
    public void Money_NegativeOrZeroAmount_Throws(decimal amount)
    {
        Assert.Throws<ArgumentException>(() => new Money(amount, "MRU"));
    }

    [Theory]
    [InlineData("USD")]
    [InlineData("EUR")]
    [InlineData("XOF")]
    public void Money_UnsupportedCurrency_Throws(string currency)
    {
        Assert.Throws<ArgumentException>(() => new Money(1000m, currency));
    }

    [Fact]
    public void Money_EmptyCurrency_Throws()
    {
        Assert.Throws<ArgumentException>(() => new Money(1000m, ""));
    }
}

// ═══════════════════════════════════════════════════════════
// TOKEN HASH
// ═══════════════════════════════════════════════════════════

public class TokenHashTests
{
    [Fact]
    public void TokenHash_ValidHash_CreatesSuccessfully()
    {
        var token = new TokenHash("a3f9b2c1d4e5f6a7");
        Assert.Equal("a3f9b2c1d4e5f6a7", token.Value);
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    public void TokenHash_EmptyOrWhitespace_Throws(string value)
    {
        Assert.Throws<ArgumentException>(() => new TokenHash(value));
    }

    [Theory]
    [InlineData("abc")]       // 3 caractères — trop court, pourrait être un numéro partiel
    [InlineData("1234567")]   // 7 caractères — juste en dessous du minimum
    public void TokenHash_TooShort_Throws(string value)
    {
        Assert.Throws<ArgumentException>(() => new TokenHash(value));
    }

    [Fact]
    public void TokenHash_IsSameAs_SameValue_ReturnsTrue()
    {
        var t1 = new TokenHash("a3f9b2c1d4e5f6a7");
        var t2 = new TokenHash("a3f9b2c1d4e5f6a7");
        Assert.True(t1.IsSameAs(t2));
    }

    [Fact]
    public void TokenHash_IsSameAs_DifferentValue_ReturnsFalse()
    {
        var t1 = new TokenHash("a3f9b2c1d4e5f6a7");
        var t2 = new TokenHash("b8c7d6e5f4a3b2c1");
        Assert.False(t1.IsSameAs(t2));
    }
}

// ═══════════════════════════════════════════════════════════
// RISK SCORE
// ═══════════════════════════════════════════════════════════

public class RiskScoreTests
{
    [Theory]
    [InlineData(0, DecisionStatus.Approve)]
    [InlineData(39, DecisionStatus.Approve)]
    [InlineData(40, DecisionStatus.Review)]
    [InlineData(69, DecisionStatus.Review)]
    [InlineData(70, DecisionStatus.Block)]
    [InlineData(100, DecisionStatus.Block)]
    public void RiskScore_ValidScoreAndDecision_CreatesSuccessfully(int score, DecisionStatus decision)
    {
        var riskScore = new RiskScore(score, decision);
        Assert.Equal(score, riskScore.Score);
        Assert.Equal(decision, riskScore.Decision);
    }

    [Theory]
    [InlineData(-1)]
    [InlineData(101)]
    public void RiskScore_ScoreOutOfRange_Throws(int score)
    {
        Assert.Throws<ArgumentOutOfRangeException>(() =>
            new RiskScore(score, DecisionStatus.Review));
    }

    [Fact]
    public void RiskScore_AlertIdOnApprove_Throws()
    {
        // Une décision APPROVE ne génère jamais d'AlertId côté FastAPI
        Assert.Throws<ArgumentException>(() =>
            new RiskScore(30, DecisionStatus.Approve, alertId: "ALT-123456789ABC"));
    }

    [Fact]
    public void RiskScore_AlertIdOnReview_AllowedWithoutThrowing()
    {
        var riskScore = new RiskScore(55, DecisionStatus.Review, alertId: "ALT-C15FDD6C8FCB");
        Assert.Equal("ALT-C15FDD6C8FCB", riskScore.AlertId);
    }

    [Fact]
    public void RiskScore_DefaultReview_HasReviewDecision()
    {
        // Le fallback Polly doit toujours retourner REVIEW — jamais APPROVE ni BLOCK
        var defaultScore = RiskScore.DefaultReview();
        Assert.Equal(DecisionStatus.Review, defaultScore.Decision);
        Assert.Equal(50, defaultScore.Score);
        Assert.Equal("UNAVAILABLE", defaultScore.FraudType);
    }

    [Fact]
    public void RiskScore_DefaultReview_RequiresHumanReview()
    {
        var defaultScore = RiskScore.DefaultReview();
        Assert.True(defaultScore.RequiresHumanReview);
    }

    [Theory]
    [InlineData(DecisionStatus.Review)]
    [InlineData(DecisionStatus.Block)]
    public void RiskScore_ReviewOrBlock_RequiresHumanReview(DecisionStatus decision)
    {
        var riskScore = new RiskScore(60, decision);
        Assert.True(riskScore.RequiresHumanReview);
    }

    [Fact]
    public void RiskScore_Approve_DoesNotRequireHumanReview()
    {
        var riskScore = new RiskScore(20, DecisionStatus.Approve);
        Assert.False(riskScore.RequiresHumanReview);
    }

    [Fact]
    public void RiskScore_IsImmutable_RecordEquality()
    {
        var s1 = new RiskScore(87, DecisionStatus.Block, fraudType: "SIM_SWAPPING");
        var s2 = new RiskScore(87, DecisionStatus.Block, fraudType: "SIM_SWAPPING");
        Assert.Equal(s1, s2); // record equality
    }
}

// ═══════════════════════════════════════════════════════════
// TRANSACTION
// ═══════════════════════════════════════════════════════════

public class TransactionTests
{
    private static TokenHash ValidToken(string suffix = "a3f9b2c1d4e5f6a7") => new(suffix);
    private static Money ValidAmount() => new(47000m, "MRU");

    [Fact]
    public void Transaction_Valid_CreatesSuccessfully()
    {
        var tx = new Transaction(
            transactionId: "BNK-2024-001",
            clientToken: ValidToken(),
            amount: ValidAmount(),
            channel: Channel.MobileApp,
            zone: "ROSSO",
            @operator: "BANKILY",
            deviceId: ValidToken("device123hash456"),
            simChanged72h: false,
            simChangedAt: null,
            beneficiaryToken: ValidToken("b8c7d6e5f4a3b2c1"),
            beneficiaryIsMerchant: false,
            agentId: null,
            ussdSession: false,
            timestamp: DateTime.UtcNow);

        Assert.Equal("BNK-2024-001", tx.TransactionId);
        Assert.Equal("BANKILY", tx.Operator);
        Assert.Equal("ROSSO", tx.Zone);
        Assert.False(tx.IsSelfTransfer);
    }

    [Fact]
    public void Transaction_UssdChannelWithoutUssdSession_Throws()
    {
        Assert.Throws<ArgumentException>(() => new Transaction(
            transactionId: "BNK-2024-001",
            clientToken: ValidToken(),
            amount: ValidAmount(),
            channel: Channel.Ussd,  // USSD mais ussdSession=false
            zone: "NOUAKCHOTT",
            @operator: "BANKILY",
            deviceId: ValidToken("device123hash456"),
            simChanged72h: false,
            simChangedAt: null,
            beneficiaryToken: ValidToken("b8c7d6e5f4a3b2c1"),
            beneficiaryIsMerchant: false,
            agentId: null,
            ussdSession: false,   // ← incohérent avec USSD
            timestamp: DateTime.UtcNow));
    }

    [Fact]
    public void Transaction_AgentIdOnNonAgentChannel_Throws()
    {
        Assert.Throws<ArgumentException>(() => new Transaction(
            transactionId: "BNK-2024-001",
            clientToken: ValidToken(),
            amount: ValidAmount(),
            channel: Channel.MobileApp,  // MobileApp mais agentId renseigné
            zone: "NOUAKCHOTT",
            @operator: "BANKILY",
            deviceId: ValidToken("device123hash456"),
            simChanged72h: false,
            simChangedAt: null,
            beneficiaryToken: ValidToken("b8c7d6e5f4a3b2c1"),
            beneficiaryIsMerchant: false,
            agentId: "AGENT-001",   // ← incohérent avec MobileApp
            ussdSession: false,
            timestamp: DateTime.UtcNow));
    }

    [Fact]
    public void Transaction_SameClientAndBeneficiaryToken_IsSelfTransfer()
    {
        var sameToken = ValidToken();
        var tx = new Transaction(
            transactionId: "BNK-2024-002",
            clientToken: sameToken,
            amount: ValidAmount(),
            channel: Channel.MobileApp,
            zone: "NOUAKCHOTT",
            @operator: "BANKILY",
            deviceId: ValidToken("device123hash456"),
            simChanged72h: false,
            simChangedAt: null,
            beneficiaryToken: sameToken,   // ← même token
            beneficiaryIsMerchant: false,
            agentId: null,
            ussdSession: false,
            timestamp: DateTime.UtcNow);

        Assert.True(tx.IsSelfTransfer);
    }

    [Fact]
    public void Transaction_OperatorNormalizesToUpperCase()
    {
        var tx = new Transaction(
            transactionId: "BNK-2024-001",
            clientToken: ValidToken(),
            amount: ValidAmount(),
            channel: Channel.MobileApp,
            zone: "rosso",
            @operator: "bankily",  // minuscules
            deviceId: ValidToken("device123hash456"),
            simChanged72h: false,
            simChangedAt: null,
            beneficiaryToken: ValidToken("b8c7d6e5f4a3b2c1"),
            beneficiaryIsMerchant: false,
            agentId: null,
            ussdSession: false,
            timestamp: DateTime.UtcNow);

        Assert.Equal("BANKILY", tx.Operator);
        Assert.Equal("ROSSO", tx.Zone);
    }
}

// ═══════════════════════════════════════════════════════════
// ALERT
// ═══════════════════════════════════════════════════════════

public class AlertTests
{
    private static RiskScore ReviewScore() =>
        new(55, DecisionStatus.Review, alertId: "ALT-C15FDD6C8FCB");

    private static RiskScore BlockScore() =>
        new(87, DecisionStatus.Block, fraudType: "SIM_SWAPPING", alertId: "ALT-C15FDD6C8FCB");

    private static RiskScore ApproveScore() =>
        new(20, DecisionStatus.Approve);

    [Fact]
    public void Alert_ValidReviewScore_CreatesSuccessfully()
    {
        var alert = new Alert("ALT-C15FDD6C8FCB", "BNK-2024-001", "BANKILY", ReviewScore(), new Money(47000m, "MRU"), DateTime.UtcNow);
        Assert.Equal(AlertStatus.Pending, alert.Status);
        Assert.True(alert.IsPending);
        Assert.False(alert.RequiresStrReport);
    }

    [Fact]
    public void Alert_ApproveScore_Throws()
    {
        // APPROVE ne génère jamais d'alerte
        Assert.Throws<ArgumentException>(() =>
            new Alert("ALT-123", "BNK-2024-001", "BANKILY", ApproveScore(), new Money(47000m, "MRU"), DateTime.UtcNow));
    }

    [Fact]
    public void Alert_Confirm_ChangesStatusAndSetsReviewer()
    {
        var alert = new Alert("ALT-C15FDD6C8FCB", "BNK-2024-001", "BANKILY", BlockScore(), new Money(47000m, "MRU"), DateTime.UtcNow);
        alert.Confirm("agent.conformite@bankily.mr", "SIM swap confirmé avec l'opérateur télécom");

        Assert.Equal(AlertStatus.Confirmed, alert.Status);
        Assert.Equal("agent.conformite@bankily.mr", alert.ReviewedBy);
        Assert.True(alert.RequiresStrReport);
        Assert.NotNull(alert.ReviewedAt);
    }

    [Fact]
    public void Alert_Dismiss_ChangesStatusToDismissed()
    {
        var alert = new Alert("ALT-C15FDD6C8FCB", "BNK-2024-001", "BANKILY", ReviewScore(), new Money(47000m, "MRU"), DateTime.UtcNow);
        alert.Dismiss("agent.conformite@bankily.mr", "Faux positif — client habituel déplacé");

        Assert.Equal(AlertStatus.Dismissed, alert.Status);
        Assert.False(alert.RequiresStrReport);
    }

    [Fact]
    public void Alert_ConfirmTwice_Throws()
    {
        var alert = new Alert("ALT-C15FDD6C8FCB", "BNK-2024-001", "BANKILY", ReviewScore(), new Money(47000m, "MRU"), DateTime.UtcNow);
        alert.Confirm("agent1@bankily.mr");

        // Un agent ne peut pas modifier une alerte déjà traitée
        Assert.Throws<InvalidOperationException>(() => alert.Confirm("agent2@bankily.mr"));
    }

    [Fact]
    public void Alert_DismissAfterConfirm_Throws()
    {
        var alert = new Alert("ALT-C15FDD6C8FCB", "BNK-2024-001", "BANKILY", ReviewScore(), new Money(47000m, "MRU"), DateTime.UtcNow);
        alert.Confirm("agent@bankily.mr");

        Assert.Throws<InvalidOperationException>(() => alert.Dismiss("agent@bankily.mr"));
    }
}

// ═══════════════════════════════════════════════════════════
// EVENTS
// ═══════════════════════════════════════════════════════════

public class DomainEventsTests
{
    [Fact]
    public void TransactionAnalyzed_ValidData_CreatesSuccessfully()
    {
        var score = new RiskScore(20, DecisionStatus.Approve);
        var evt = new TransactionAnalyzed("BNK-2024-001", "BANKILY", score);

        Assert.Equal("BNK-2024-001", evt.TransactionId);
        Assert.Equal("BANKILY", evt.Operator);
        Assert.True(evt.OccurredAt <= DateTime.UtcNow);
    }

    [Fact]
    public void FraudDetected_ApproveScore_Throws()
    {
        // FraudDetected ne peut être émis que pour REVIEW ou BLOCK
        var approveScore = new RiskScore(20, DecisionStatus.Approve);
        Assert.Throws<ArgumentException>(() =>
            new FraudDetected("BNK-2024-001", "BANKILY", approveScore));
    }

    [Fact]
    public void FraudDetected_BlockScore_CreatesSuccessfully()
    {
        var blockScore = new RiskScore(87, DecisionStatus.Block,
            fraudType: "SIM_SWAPPING", alertId: "ALT-C15FDD6C8FCB");
        var evt = new FraudDetected("BNK-2024-001", "BANKILY", blockScore);

        Assert.Equal(DecisionStatus.Block, evt.Decision);
        Assert.Equal("SIM_SWAPPING", evt.FraudType);
    }

    [Fact]
    public void TransactionAnalyzed_EmptyTransactionId_Throws()
    {
        var score = new RiskScore(20, DecisionStatus.Approve);
        Assert.Throws<ArgumentException>(() =>
            new TransactionAnalyzed("", "BANKILY", score));
    }
}