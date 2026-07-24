using FraudDetection.Application.Interfaces;
using FraudDetection.Infrastructure.Adapters;
using Microsoft.Extensions.Logging.Abstractions;
using Moq;
using Xunit;

namespace FraudDetection.Tests.Infrastructure;

public class OperatorAdapterRegistryTests
{
    private static Mock<IOperatorWebhookAdapter> BuildAdapterMock(
        bool canHandle, bool isFallback)
    {
        var mock = new Mock<IOperatorWebhookAdapter>();
        mock.Setup(a => a.CanHandle(It.IsAny<string>())).Returns(canHandle);
        mock.Setup(a => a.IsFallback).Returns(isFallback);
        return mock;
    }

    [Fact]
    public void Resolve_OnlySpecificMatches_ReturnsSpecific()
    {
        var specific = BuildAdapterMock(canHandle: true, isFallback: false);
        var registry = new OperatorAdapterRegistry(
            new[] { specific.Object }, NullLogger<OperatorAdapterRegistry>.Instance);

        var result = registry.Resolve("BANKILY");

        Assert.Same(specific.Object, result);
    }

    [Fact]
    public void Resolve_OnlyFallbackMatches_ReturnsFallback()
    {
        var fallback = BuildAdapterMock(canHandle: true, isFallback: true);
        var registry = new OperatorAdapterRegistry(
            new[] { fallback.Object }, NullLogger<OperatorAdapterRegistry>.Instance);

        var result = registry.Resolve("SEDAD");

        Assert.Same(fallback.Object, result);
    }

    [Fact]
    public void Resolve_BothMatch_PrefersSpecificOverFallback()
    {
        // LE TEST CRITIQUE de ce fichier — reproduit exactement le risque
        // identifié : un adaptateur spécifique ET le fallback générique
        // répondent tous les deux CanHandle("BANKILY") = true. Le registre
        // doit systématiquement préférer le spécifique.
        var specific = BuildAdapterMock(canHandle: true, isFallback: false);
        var fallback = BuildAdapterMock(canHandle: true, isFallback: true);

        // Ordre d'enregistrement volontairement inversé (fallback en premier)
        // pour prouver que la sélection ne dépend PAS de l'ordre du DI.
        var registry = new OperatorAdapterRegistry(
            new[] { fallback.Object, specific.Object },
            NullLogger<OperatorAdapterRegistry>.Instance);

        var result = registry.Resolve("BANKILY");

        Assert.Same(specific.Object, result);
        Assert.NotSame(fallback.Object, result);
    }

    [Fact]
    public void Resolve_NoAdapterMatches_ReturnsNull()
    {
        var adapter = BuildAdapterMock(canHandle: false, isFallback: true);
        var registry = new OperatorAdapterRegistry(
            new[] { adapter.Object }, NullLogger<OperatorAdapterRegistry>.Instance);

        var result = registry.Resolve("INCONNU");

        Assert.Null(result);
    }

    [Fact]
    public void Resolve_EmptyAdapterList_ReturnsNull()
    {
        var registry = new OperatorAdapterRegistry(
            Array.Empty<IOperatorWebhookAdapter>(), NullLogger<OperatorAdapterRegistry>.Instance);

        var result = registry.Resolve("BANKILY");

        Assert.Null(result);
    }

    [Fact]
    public void Resolve_MultipleSpecificAdapters_ReturnsFirstMatching()
    {
        var specificA = BuildAdapterMock(canHandle: false, isFallback: false);
        var specificB = BuildAdapterMock(canHandle: true, isFallback: false);

        var registry = new OperatorAdapterRegistry(
            new[] { specificA.Object, specificB.Object },
            NullLogger<OperatorAdapterRegistry>.Instance);

        var result = registry.Resolve("MASRVI");

        Assert.Same(specificB.Object, result);
    }
}