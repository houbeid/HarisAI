namespace FraudDetection.Infrastructure.Auth;

/// <summary>
/// Fournit le secret HMAC partagé pour un opérateur donné.
/// Reste interne à Infrastructure/Auth — ni le Domain ni l'Application
/// n'ont besoin de connaître ce mécanisme, c'est un détail de la couche
/// d'authentification HTTP.
///
/// UN SECRET PAR OPÉRATEUR, PAS UN SECRET GLOBAL : si le secret d'un
/// opérateur est compromis, seule sa clé doit être révoquée — les autres
/// opérateurs restent protégés. Cohérent avec le déploiement isolé par site
/// (chaque site n'héberge qu'un seul opérateur, donc en pratique un seul
/// secret actif par déploiement, mais le contrat reste multi-opérateur
/// pour ne pas coupler cette interface à l'hypothèse mono-site).
///
/// STOCKAGE : l'implémentation concrète (OperatorSecretProvider) lit depuis
/// la configuration .NET (appsettings / variables d'environnement), jamais
/// en dur dans le code — voir la note de sécurité sur les secrets dans
/// l'architecture (jamais dans l'image Docker ni le repo).
/// </summary>
public interface IOperatorSecretProvider
{
    /// <summary>
    /// Retourne le secret HMAC (en bytes, prêt pour HMACSHA256) associé
    /// au code opérateur donné. Retourne null si aucun secret n'est
    /// configuré pour cet opérateur — le Handler doit alors rejeter
    /// la requête plutôt que de tenter une validation avec un secret vide.
    /// </summary>
    byte[]? GetSecret(string operatorCode);
}