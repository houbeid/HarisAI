using System.Net;
using FluentValidation;
using FraudDetection.API.Hubs;
using FraudDetection.API.Middleware;
using FraudDetection.Application.Behaviors;
using FraudDetection.Application.Commands.AnalyzeTransaction;
using FraudDetection.Application.Interfaces;
using FraudDetection.Infrastructure.Adapters;
using FraudDetection.Infrastructure.Auth;
using FraudDetection.Infrastructure.Caching;
using FraudDetection.Infrastructure.ExternalServices;
using FraudDetection.Infrastructure.Observability;
using FraudDetection.Infrastructure.Persistence;
using MediatR;
using Microsoft.EntityFrameworkCore;
using Polly;
using Polly.Extensions.Http;
using Serilog;

var builder = WebApplication.CreateBuilder(args);

// ═══════════════════════════════════════════════════════════════════════
// LOGGING — Serilog, avec CorrelationId injecté automatiquement par
// CorrelationIdMiddleware via LogContext (voir ce fichier)
// ═══════════════════════════════════════════════════════════════════════

builder.Host.UseSerilog((context, loggerConfig) =>
    loggerConfig
        .ReadFrom.Configuration(context.Configuration)
        .Enrich.FromLogContext()
        .WriteTo.Console(
            outputTemplate:
            "[{Timestamp:HH:mm:ss} {Level:u3}] {CorrelationId} {SourceContext}: {Message:lj}{NewLine}{Exception}"));

// ═══════════════════════════════════════════════════════════════════════
// APPLICATION — MediatR, FluentValidation, pipeline de validation
// ═══════════════════════════════════════════════════════════════════════

builder.Services.AddMediatR(cfg =>
    cfg.RegisterServicesFromAssemblyContaining<AnalyzeTransactionCommand>());

// Enregistre tous les IValidator<T> du projet Application (FluentValidation) —
// sans ValidationBehavior (pipeline MediatR), ces validateurs existeraient
// mais ne seraient jamais invoqués automatiquement.
builder.Services.AddValidatorsFromAssemblyContaining<AnalyzeTransactionCommand>();
builder.Services.AddTransient(
    typeof(IPipelineBehavior<,>), typeof(ValidationBehavior<,>));

// ═══════════════════════════════════════════════════════════════════════
// PERSISTENCE — PostgreSQL local au site, schéma fraud_backend
// ═══════════════════════════════════════════════════════════════════════

var postgresConnectionString = builder.Configuration.GetConnectionString("Postgres")
    ?? throw new InvalidOperationException(
        "ConnectionStrings:Postgres manquante — obligatoire pour démarrer.");

builder.Services.AddDbContext<AppDbContext>(options =>
    options
        .UseNpgsql(postgresConnectionString)
        .UseSnakeCaseNamingConvention()); // convention identique à celle des tests

builder.Services.AddScoped<IAlertRepository, AlertRepository>();
builder.Services.AddScoped<ITransactionRepository, TransactionRepository>();
builder.Services.AddScoped<IPendingTransactionQueue, PendingTransactionRepository>();
builder.Services.AddScoped<IStrReportRepository, StrReportRepository>();

// ═══════════════════════════════════════════════════════════════════════
// ADAPTERS — registre d'adaptateurs opérateurs
// ═══════════════════════════════════════════════════════════════════════

// GenericMobileMoneyWebhookAdapter reste enregistré tant qu'aucun accord
// spécifique n'est signé — voir sa documentation. Un futur BankilyWebhookAdapter
// (format réel) se rajoutera ici avec la même ligne AddScoped, sans rien
// modifier d'autre — c'est tout l'intérêt du registre.
builder.Services.AddScoped<IOperatorWebhookAdapter, GenericMobileMoneyWebhookAdapter>();
builder.Services.AddScoped<IOperatorAdapterRegistry, OperatorAdapterRegistry>();

builder.Services.AddScoped<ISimChangeService, SimChangeService>();

// ═══════════════════════════════════════════════════════════════════════
// CLIENT HTTP VERS FRAUD-ML-SERVICE — HttpClient typé + Polly
// ═══════════════════════════════════════════════════════════════════════

var fastApiBaseUrl = builder.Configuration["FastApi:BaseUrl"]
    ?? throw new InvalidOperationException("FastApi:BaseUrl manquante.");
var fastApiKey = builder.Configuration["FastApi:ApiKey"]
    ?? throw new InvalidOperationException("FastApi:ApiKey manquante.");

builder.Services
    .AddHttpClient<IMlScoringService, MlScoringService>(client =>
    {
        client.BaseAddress = new Uri(fastApiBaseUrl);
        client.DefaultRequestHeaders.Add("X-Api-Key", fastApiKey);
        client.Timeout = TimeSpan.FromSeconds(10);
    })
    .AddPolicyHandler(GetRetryPolicy())
    .AddPolicyHandler(GetCircuitBreakerPolicy());

// ═══════════════════════════════════════════════════════════════════════
// AUTHENTIFICATION — deux schémas distincts, jamais mélangés
// ═══════════════════════════════════════════════════════════════════════

builder.Services.AddSingleton<IOperatorSecretProvider, OperatorSecretProvider>();

var jwtOptions = builder.Configuration
    .GetSection(JwtAuthenticationOptions.ConfigSectionName)
    .Get<JwtAuthenticationOptions>()
    ?? throw new InvalidOperationException(
        $"Section de configuration '{JwtAuthenticationOptions.ConfigSectionName}' manquante.");

builder.Services.AddAuthentication()
    .AddScheme<HmacAuthenticationOptions, HmacAuthenticationHandler>("Hmac", _ => { })
    .AddJwtAuthentication(jwtOptions);

builder.Services.AddAuthorization();

// ═══════════════════════════════════════════════════════════════════════
// SIGNALR — AlertHub + backplane Redis (obligatoire dès plusieurs pods)
// ═══════════════════════════════════════════════════════════════════════

var redisConnectionString = builder.Configuration.GetConnectionString("Redis")
    ?? throw new InvalidOperationException("ConnectionStrings:Redis manquante.");

builder.Services
    .AddSignalR()
    .AddRedisBackplane(redisConnectionString);

builder.Services.AddScoped<IAlertNotifier, SignalRAlertNotifier>();

// ═══════════════════════════════════════════════════════════════════════
// OBSERVABILITÉ — métriques Prometheus + poller de jauges + healthcheck
// ═══════════════════════════════════════════════════════════════════════

builder.Services.AddSingleton<IMetricsCollector, MetricsCollector>();
builder.Services.AddHostedService<PendingMetricsPoller>();

builder.Services.AddHealthChecks()
    // "ready" uniquement — un pod avec FastAPI down ne doit jamais être
    // redémarré par K8s (liveness), juste sorti temporairement de la
    // rotation du Service (readiness). Voir FraudMlServiceHealthCheck.
    .AddCheck<FraudMlServiceHealthCheck>("fraud-ml-service", tags: new[] { "ready" });

builder.Services.AddControllers();

// ═══════════════════════════════════════════════════════════════════════
// POLITIQUES POLLY — retry + circuit breaker vers fraud-ml-service
// ═══════════════════════════════════════════════════════════════════════

static IAsyncPolicy<HttpResponseMessage> GetRetryPolicy() =>
    HttpPolicyExtensions
        .HandleTransientHttpError() // 5xx, 408, HttpRequestException
        .OrResult(msg => msg.StatusCode == HttpStatusCode.TooManyRequests) // 429 rate limit FastAPI
        .WaitAndRetryAsync(
            retryCount: 3,
            sleepDurationProvider: attempt => TimeSpan.FromMilliseconds(200 * Math.Pow(2, attempt)));

static IAsyncPolicy<HttpResponseMessage> GetCircuitBreakerPolicy() =>
    HttpPolicyExtensions
        .HandleTransientHttpError()
        .CircuitBreakerAsync(
            handledEventsAllowedBeforeBreaking: 5,
            durationOfBreak: TimeSpan.FromSeconds(30));

// ═══════════════════════════════════════════════════════════════════════
// PIPELINE HTTP
// ═══════════════════════════════════════════════════════════════════════

var app = builder.Build();

// CorrelationIdMiddleware doit être enregistré très tôt — avant
// UseAuthentication — pour que même les requêtes rejetées par
// l'authentification (401/403) aient un CorrelationId dans leurs logs.
app.UseMiddleware<CorrelationIdMiddleware>();

// GlobalExceptionMiddleware juste après — intercepte toute exception levée
// plus loin dans le pipeline (MediatR/Handlers via les Controllers), avec
// le CorrelationId déjà disponible dans le contexte de log. Traduit
// ValidationException / OperatorNotConfiguredException / AlertNotFoundException /
// AlertAlreadyProcessedException en réponses JSON cohérentes pour toute l'API
// — plus de try/catch dupliqué dans TransactionController ou AlertController.
app.UseMiddleware<GlobalExceptionMiddleware>();

app.UseRouting();
app.UseAuthentication();
app.UseAuthorization();

// Applique automatiquement les migrations EF Core au démarrage —
// acceptable pour un déploiement mono-instance ; à revoir si un Job K8s
// dédié à la migration est mis en place (voir point ouvert de l'architecture
// fraud-infrastructure sur l'ordre de déploiement, migration-job.yaml).
using (var scope = app.Services.CreateScope())
{
    var dbContext = scope.ServiceProvider.GetRequiredService<AppDbContext>();
    dbContext.Database.Migrate();
}

app.MapHealthChecks("/health/live", new()
{
    Predicate = _ => false, // aucun check exécuté — juste "le process répond"
    ResponseWriter = WriteHealthCheckJsonResponse
});
app.MapHealthChecks("/health/ready", new()
{
    Predicate = check => check.Tags.Contains("ready"),
    ResponseWriter = WriteHealthCheckJsonResponse
});

app.MapMetrics(); // /metrics — prometheus-net

app.MapControllers();
app.MapHub<AlertHub>("/alertHub");

app.Run();

// ═══════════════════════════════════════════════════════════════════════
// RÉPONSE JSON DÉTAILLÉE POUR LES HEALTHCHECKS — remplace le texte brut
// par défaut ("Healthy"/"Unhealthy") par un JSON structuré exploitable
// par un dashboard de supervision ou une sonde K8s qui inspecte le corps
// de la réponse, pas seulement le code HTTP.
// ═══════════════════════════════════════════════════════════════════════
static Task WriteHealthCheckJsonResponse(
    HttpContext context,
    Microsoft.Extensions.Diagnostics.HealthChecks.HealthReport report)
{
    context.Response.ContentType = "application/json";

    var payload = new
    {
        status = report.Status.ToString(),
        totalDurationMs = report.TotalDuration.TotalMilliseconds,
        checks = report.Entries.Select(entry => new
        {
            name = entry.Key,
            status = entry.Value.Status.ToString(),
            description = entry.Value.Description,
            durationMs = entry.Value.Duration.TotalMilliseconds
        })
    };

    return context.Response.WriteAsync(
        System.Text.Json.JsonSerializer.Serialize(payload));
}

// Nécessaire pour que WebApplicationFactory<Program> fonctionne dans de
// futurs tests d'intégration complets de l'API.
public partial class Program { }