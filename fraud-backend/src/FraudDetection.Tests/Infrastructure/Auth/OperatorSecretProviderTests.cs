using FraudDetection.Infrastructure.Auth;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging.Abstractions;
using Xunit;

namespace FraudDetection.Tests.Infrastructure.Auth;

public class OperatorSecretProviderTests
{
    private static OperatorSecretProvider BuildProvider(
        Dictionary<string, string?> configValues)
    {
        var configuration = new ConfigurationBuilder()
            .AddInMemoryCollection(configValues)
            .Build();

        return new OperatorSecretProvider(
            configuration, NullLogger<OperatorSecretProvider>.Instance);
    }

    [Fact]
    public void GetSecret_ConfiguredOperator_ReturnsSecretBytes()
    {
        var provider = BuildProvider(new()
        {
            ["OperatorSecrets:BANKILY"] = "this-is-a-valid-test-secret-32chars"
        });

        var secret = provider.GetSecret("BANKILY");

        Assert.NotNull(secret);
        Assert.Equal(
            "this-is-a-valid-test-secret-32chars",
            System.Text.Encoding.UTF8.GetString(secret!));
    }

    [Fact]
    public void GetSecret_UnknownOperator_ReturnsNull()
    {
        var provider = BuildProvider(new()
        {
            ["OperatorSecrets:BANKILY"] = "this-is-a-valid-test-secret-32chars"
        });

        var secret = provider.GetSecret("SEDAD");

        Assert.Null(secret);
    }

    [Fact]
    public void GetSecret_LowercaseOperatorCode_ResolvesCaseInsensitively()
    {
        var provider = BuildProvider(new()
        {
            ["OperatorSecrets:BANKILY"] = "this-is-a-valid-test-secret-32chars"
        });

        var secret = provider.GetSecret("bankily");

        Assert.NotNull(secret);
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    public void GetSecret_EmptyOrWhitespaceOperatorCode_ReturnsNull(string operatorCode)
    {
        var provider = BuildProvider(new()
        {
            ["OperatorSecrets:BANKILY"] = "this-is-a-valid-test-secret-32chars"
        });

        var secret = provider.GetSecret(operatorCode);

        Assert.Null(secret);
    }

    [Fact]
    public void GetSecret_ShortSecret_StillReturnsIt()
    {
        // Un secret court déclenche un LogWarning mais n'est pas bloquant —
        // vérifie que le comportement fonctionnel reste correct malgré l'alerte.
        var provider = BuildProvider(new()
        {
            ["OperatorSecrets:BANKILY"] = "short"
        });

        var secret = provider.GetSecret("BANKILY");

        Assert.NotNull(secret);
        Assert.Equal("short", System.Text.Encoding.UTF8.GetString(secret!));
    }

    [Fact]
    public void GetSecret_EmptyConfiguration_ReturnsNull()
    {
        var provider = BuildProvider(new());

        var secret = provider.GetSecret("BANKILY");

        Assert.Null(secret);
    }
}