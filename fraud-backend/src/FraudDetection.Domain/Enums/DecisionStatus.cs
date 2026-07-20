namespace FraudDetection.Domain.Enums;

/// <summary>
/// Miroir exact du champ "decision" retourné par FastAPI dans ScoreOut.
/// APPROVE = score inférieur à 40
/// REVIEW  = score entre 40 et 69
/// BLOCK   = score supérieur ou égal à 70
///
/// IMPORTANT : .NET ne recalcule jamais cette décision — elle est exclusivement
/// déterminée côté Python par FraudScore.compute(). RiskScore.cs reflète ce résultat,
/// il ne le reproduit pas.
/// </summary>
public enum DecisionStatus
{
    Approve,
    Review,
    Block
}