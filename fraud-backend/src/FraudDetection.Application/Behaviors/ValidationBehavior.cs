using FluentValidation;
using MediatR;

namespace FraudDetection.Application.Behaviors;

/// <summary>
/// Pipeline behavior MediatR — invoque automatiquement tous les
/// IValidator&lt;TRequest&gt; enregistrés dans le DI avant que le Handler
/// ne soit exécuté. Sans ce fichier, un validateur comme
/// AnalyzeTransactionCommandValidator existe mais n'est jamais appelé —
/// MediatR ne connaît pas FluentValidation nativement.
///
/// S'applique à TOUTES les Commands/Queries qui ont un validateur associé,
/// sans qu'aucun Handler n'ait à appeler la validation lui-même — cohérent
/// avec la séparation déjà documentée dans AnalyzeTransactionCommandValidator :
/// validation structurelle (ce fichier) vs validation métier (le Handler).
///
/// Enregistré dans Program.cs via :
///   builder.Services.AddTransient(
///       typeof(IPipelineBehavior&lt;,&gt;), typeof(ValidationBehavior&lt;,&gt;));
/// </summary>
public sealed class ValidationBehavior<TRequest, TResponse>
    : IPipelineBehavior<TRequest, TResponse>
    where TRequest : IRequest<TResponse>
{
    private readonly IEnumerable<IValidator<TRequest>> _validators;

    public ValidationBehavior(IEnumerable<IValidator<TRequest>> validators)
    {
        _validators = validators;
    }

    public async Task<TResponse> Handle(
        TRequest request,
        RequestHandlerDelegate<TResponse> next,
        CancellationToken cancellationToken)
    {
        // Pas de validateur enregistré pour ce type de requête (ex: les
        // Queries n'en ont généralement pas) — on passe directement au Handler.
        if (!_validators.Any())
        {
            return await next();
        }

        var context = new ValidationContext<TRequest>(request);

        var failures = (await Task.WhenAll(
                _validators.Select(v => v.ValidateAsync(context, cancellationToken))))
            .SelectMany(result => result.Errors)
            .Where(failure => failure is not null)
            .ToList();

        if (failures.Count > 0)
        {
            // ValidationException (FluentValidation) — à traduire en 400 Bad Request
            // par un middleware de gestion d'erreurs global côté API, pas ici.
            // L'Application ne connaît pas HTTP.
            throw new ValidationException(failures);
        }

        return await next();
    }
}