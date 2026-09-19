using FraudDetection.Application.Exceptions;
using FraudDetection.Application.Interfaces;
using FraudDetection.Domain.Entities;
using MediatR;
using Microsoft.Extensions.Logging;

namespace FraudDetection.Application.Queries.GetAlertById;

/// <summary>
/// Requête MediatR pour récupérer une alerte unique par son AlertId.
/// Utilisée par AlertController (GET /alerts/{alertId}) — comble le
/// point ouvert 4 réclamé par la session frontend : après un conflit 409
/// (alerte déjà traitée par un autre agent), le dashboard n'avait aucun
/// moyen fiable de relire l'état exact de CETTE alerte sans dépendre de
/// la fenêtre de pagination de GET /alerts.
/// </summary>
public sealed record GetAlertByIdQuery(string AlertId) : IRequest<Alert>;

/// <summary>
/// Handler de récupération d'une alerte unique.
/// Réutilise IAlertRepository.GetByAlertIdAsync — déjà existant, déjà
/// utilisé par ValidateAlertHandler pour la même recherche. Aucune
/// nouvelle méthode de repository nécessaire.
///
/// Lève AlertNotFoundException (→ 404 via GlobalExceptionMiddleware) si
/// l'alerte n'existe pas — même type d'exception que ValidateAlertHandler,
/// cohérence du contrat d'erreur entre les deux endpoints.
/// </summary>
public sealed class GetAlertByIdHandler : IRequestHandler<GetAlertByIdQuery, Alert>
{
    private readonly IAlertRepository _alertRepository;
    private readonly ILogger<GetAlertByIdHandler> _logger;

    public GetAlertByIdHandler(
        IAlertRepository alertRepository,
        ILogger<GetAlertByIdHandler> logger)
    {
        _alertRepository = alertRepository;
        _logger = logger;
    }

    public async Task<Alert> Handle(
        GetAlertByIdQuery request,
        CancellationToken cancellationToken)
    {
        var alert = await _alertRepository.GetByAlertIdAsync(
            request.AlertId, cancellationToken);

        if (alert is null)
        {
            _logger.LogWarning(
                "GetAlertById — alerte introuvable — AlertId={AlertId}",
                request.AlertId);

            throw new AlertNotFoundException(request.AlertId);
        }

        return alert;
    }
}