using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.SignalR;

namespace FraudDetection.API.Hubs;

/// <summary>
/// Hub SignalR pour la notification temps réel des agents de conformité
/// connectés à fraud-dashboard. Protégé par le schéma "Jwt" — un agent
/// doit être authentifié pour ouvrir la connexion WebSocket.
///
/// AUCUNE MÉTHODE APPELABLE PAR LE CLIENT : ce Hub ne fait que recevoir
/// des connexions — toute la diffusion se fait dans l'AUTRE sens, depuis
/// le serveur vers les clients connectés, déclenchée par CreateAlertHandler
/// via IAlertNotifier (voir SignalRAlertNotifier.cs) quand une nouvelle
/// alerte REVIEW/BLOCK est créée.
///
/// PAS DE GROUPES PAR OPÉRATEUR : conformément à la topologie de déploiement
/// (un site = un opérateur), tous les agents connectés à cette instance
/// travaillent pour le même opérateur — diffuser à tous les clients connectés
/// est donc correct et plus simple qu'un système de groupes qui n'aurait
/// aucune utilité réelle ici.
///
/// BACKPLANE REDIS OBLIGATOIRE dès plusieurs pods (voir RedisService.cs,
/// déjà câblé dans Program.cs) — sans lui, un agent connecté au pod A ne
/// recevrait jamais une alerte créée par un traitement sur le pod B.
/// </summary>
[Authorize(AuthenticationSchemes = "Jwt")]
public sealed class AlertHub : Hub
{
    // Volontairement vide — ce Hub n'expose aucune méthode côté client.
    // La classe existe pour fournir le point de terminaison WebSocket
    // (/alertHub, voir Program.cs) et le contexte d'authentification/
    // autorisation ; toute la logique de diffusion vit dans
    // SignalRAlertNotifier.cs, appelé depuis l'Application via IAlertNotifier.
}