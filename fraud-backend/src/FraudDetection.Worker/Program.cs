using System.Net;
using FluentValidation;
using FraudDetection.Application.Behaviors;
using FraudDetection.Application.Commands.CreateAlert;
using FraudDetection.Application.Interfaces;
using FraudDetection.Infrastructure.ExternalServices;
using FraudDetection.Infrastructure.Observability;
using FraudDetection.Infrastructure.Persistence;
using FraudDetection.Worker;
using MediatR;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Polly;
using Polly.Extensions.Http;
using Serilog;

var builder = Host.CreateApplicationBuilder(args);

// ═══════════════════════════════════════════════════════════════════════
// LOGGING — Serilog générique (pas de LogContext par requête HTTP ici,
// le Worker n'a pas de pipeline HTTP ; PendingTransactionWorker pousse
// lui-même un CorrelationId par tentative de rescoring, voir ce fichier)
// ═══════════════════════════════════════════════════════════════════════

builder.Services.AddSerilog((services, loggerConfig) =>
    loggerConfig
        .ReadFrom.Configuration(services.GetRequiredService<IConfiguration>())
        .Enrich.FromLogContext()
        .WriteTo.Console(
            outputTemplate:
            "[{Timestamp:HH:mm:ss} {Level:u3}] {CorrelationId} {SourceContext}: {Message:lj}{NewLine}{Exception}"));

// ═══════════════════════════════════════════════════════════════════════
// APPLICATION — MediatR (uniquement pour CreateAlertCommand, déclenché
// après un rescoring réussi en REVIEW/BLOCK), validation
// ═══════════════════════════════════════════════════════════════════════

builder.Services.AddMediatR(cfg =>
    cfg.RegisterServicesFromAssemblyContaining<CreateAlertCommand>());

builder.Services.AddValidatorsFromAssemblyContaining<CreateAlertCommand>();
builder.Services.AddTransient(
    typeof(IPipelineBehavior<,>), typeof(ValidationBehavior<,>));

// ═══════════════════════════════════════════════════════════════════════
// PERSISTENCE — même base PostgreSQL locale que l'API, même convention
// ═══════════════════════════════════════════════════════════════════════

var postgresConnectionString = builder.Configuration.GetConnectionString("Postgres")
    ?? throw new InvalidOperationException(
        "ConnectionStrings:Postgres manquante — obligatoire pour démarrer.");

builder.Services.AddDbContext<AppDbContext>(options =>
    options
        .UseNpgsql(postgresConnectionString)
        .UseSnakeCaseNamingConvention());

builder.Services.AddScoped<IAlertRepository, AlertRepository>();
builder.Services.AddScoped<ITransactionRepository, TransactionRepository>();
builder.Services.AddScoped<IPendingTransactionQueue, PendingTransactionRepository>();

// Pas de SignalR ici — voir NoOpAlertNotifier.cs pour le raisonnement complet.
builder.Services.AddScoped<IAlertNotifier, NoOpAlertNotifier>();

// ═══════════════════════════════════════════════════════════════════════
// CLIENT HTTP VERS FRAUD-ML-SERVICE — même politique Polly que l'API
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

static IAsyncPolicy<HttpResponseMessage> GetRetryPolicy() =>
    HttpPolicyExtensions
        .HandleTransientHttpError()
        .OrResult(msg => msg.StatusCode == HttpStatusCode.TooManyRequests)
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
// OBSERVABILITÉ — IMetricsCollector enregistré pour que MlScoringService
// fonctionne sans erreur DI, MAIS aucun endpoint /metrics exposé depuis
// ce process (le Worker n'est pas un serveur web). Les métriques
// enregistrées ici vivent dans un registre Prometheus séparé de celui
// de l'API — LIMITE CONNUE, non résolue (nécessiterait un mini-listener
// HTTP dédié dans le Worker pour être scrapées indépendamment).
// ═══════════════════════════════════════════════════════════════════════

builder.Services.AddSingleton<IMetricsCollector, MetricsCollector>();

// ═══════════════════════════════════════════════════════════════════════
// LE WORKER LUI-MÊME
// ═══════════════════════════════════════════════════════════════════════

builder.Services.AddHostedService<PendingTransactionWorker>();

var host = builder.Build();
host.Run();