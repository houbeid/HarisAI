using System.Text;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using Microsoft.IdentityModel.Tokens;

namespace FraudDetection.Infrastructure.Auth;

/// <summary>
/// Câble l'authentification JWT pour les sessions humaines (fraud-dashboard)
/// en s'appuyant sur JwtBearerHandler — l'implémentation officielle Microsoft,
/// pas une réécriture custom. Contrairement à HmacAuthenticationHandler
/// (schéma propriétaire sans équivalent standard), la validation JWT est un
/// problème déjà résolu et éprouvé — le réimplémenter à la main serait un
/// risque de sécurité inutile.
///
/// SCHÉMA "Jwt" — protège AlertController et ReportController.
/// Distinct du schéma "Hmac" qui protège exclusivement TransactionController.
///
/// USAGE dans Program.cs :
///   var jwtOptions = builder.Configuration
///       .GetSection(JwtAuthenticationOptions.ConfigSectionName)
///       .Get&lt;JwtAuthenticationOptions&gt;()!;
///
///   builder.Services.AddAuthentication()
///       .AddScheme&lt;HmacAuthenticationOptions, HmacAuthenticationHandler&gt;("Hmac", null)
///       .AddJwtAuthentication(jwtOptions);
/// </summary>
public static class JwtAuthenticationHandler
{
    public const string SchemeName = "Jwt";

    public static AuthenticationBuilder AddJwtAuthentication(
        this AuthenticationBuilder builder,
        JwtAuthenticationOptions options)
    {
        var signingKey = new SymmetricSecurityKey(
            Encoding.UTF8.GetBytes(options.SigningKey));

        return builder.AddJwtBearer(SchemeName, jwtOptions =>
        {
            jwtOptions.TokenValidationParameters = new TokenValidationParameters
            {
                ValidateIssuer = true,
                ValidIssuer = options.Issuer,

                ValidateAudience = true,
                ValidAudience = options.Audience,

                ValidateIssuerSigningKey = true,
                IssuerSigningKey = signingKey,

                ValidateLifetime = true,
                ClockSkew = options.ClockSkew,

                RoleClaimType = options.RoleClaimType,

                // NameClaimType par défaut ("sub") convient pour identifier
                // l'agent dans les logs (ReviewedBy dans ValidateAlertCommand).
            };

            // Logging explicite des échecs d'authentification — sans ça,
            // un token expiré ou mal signé échoue silencieusement côté
            // client (401 générique) sans trace exploitable côté serveur.
            jwtOptions.Events = new JwtBearerEvents
            {
                OnAuthenticationFailed = context =>
                {
                    var logger = context.HttpContext.RequestServices
                        .GetRequiredService<ILoggerFactory>()
                        .CreateLogger(nameof(JwtAuthenticationHandler));

                    logger.LogWarning(
                        context.Exception,
                        "Échec de validation JWT — {ExceptionType}: {Message}",
                        context.Exception.GetType().Name,
                        context.Exception.Message);

                    return Task.CompletedTask;
                },
                OnChallenge = context =>
                {
                    var logger = context.HttpContext.RequestServices
                        .GetRequiredService<ILoggerFactory>()
                        .CreateLogger(nameof(JwtAuthenticationHandler));

                    logger.LogDebug(
                        "Challenge JWT déclenché — requête non authentifiée vers {Path}",
                        context.HttpContext.Request.Path);

                    return Task.CompletedTask;
                }
            };
        });
    }
}