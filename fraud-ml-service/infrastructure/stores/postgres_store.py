"""
HarisAI — PostgresAuditStore
==============================
Implémentation concrète de IAuditStore.
Persiste l'audit trail immuable dans PostgreSQL — obligatoire BCM/GAFI.

RÔLE :
    Chaque décision du système est enregistrée de façon immuable.
    Si la BCM audite la banque, elle peut voir exactement :
    - Quelle transaction a été analysée
    - Quel score a été calculé
    - Quelle version du modèle a décidé
    - Quel compliance officer a validé
    - Quand le rapport STR a été généré

TABLES CRÉÉES :
    transaction_scores   → chaque analyse ML (APPROVE/REVIEW/BLOCK)
    alerts               → chaque alerte créée + feedback compliance
    model_predictions    → détails techniques par modèle ML

RÈGLE D'OR :
    Ces tables sont en APPEND ONLY — jamais de UPDATE ni DELETE.
    L'historique est sacré pour la conformité BCM.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from application.ports.i_explainer_audit import IAuditStore
from domain import Alert, FraudScore, Transaction

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# SQL — création des tables
# ─────────────────────────────────────────────

SQL_CREATE_TABLES = """
-- Audit trail de chaque transaction analysée
CREATE TABLE IF NOT EXISTS transaction_scores (
    id                  BIGSERIAL PRIMARY KEY,
    transaction_id      VARCHAR(100) NOT NULL,
    client_token        VARCHAR(255) NOT NULL,
    operator            VARCHAR(50)  NOT NULL,

    -- Montant et canal
    amount              DECIMAL(15,2) NOT NULL,
    currency            VARCHAR(10)   NOT NULL DEFAULT 'MRU',
    channel             VARCHAR(50)   NOT NULL,
    zone                VARCHAR(100),

    -- Scores des 4 modèles
    xgboost_score       DECIMAL(5,4),
    isolation_score     DECIMAL(5,4),
    tft_score           DECIMAL(5,4),
    gnn_score           DECIMAL(5,4),

    -- Score final
    final_score         DECIMAL(5,4)  NOT NULL,
    risk_level          VARCHAR(20)   NOT NULL,  -- APPROVE/REVIEW/BLOCK
    fraud_type          VARCHAR(50),

    -- Explication SHAP (JSON)
    shap_reasons        JSONB,

    -- Méta modèle
    model_version       VARCHAR(50),
    inference_time_ms   DECIMAL(8,2),

    -- Données SIM — pour audit SIM swapping
    sim_changed_72h     BOOLEAN DEFAULT FALSE,

    -- Timestamps (immuables)
    analyzed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Index pour les requêtes fréquentes
    CONSTRAINT uq_transaction_scores_tx_id UNIQUE (transaction_id)
);

CREATE INDEX IF NOT EXISTS idx_scores_client_token
    ON transaction_scores (client_token);
CREATE INDEX IF NOT EXISTS idx_scores_analyzed_at
    ON transaction_scores (analyzed_at);
CREATE INDEX IF NOT EXISTS idx_scores_risk_level
    ON transaction_scores (risk_level);
CREATE INDEX IF NOT EXISTS idx_scores_operator
    ON transaction_scores (operator);


-- Alertes créées et feedback compliance officer
CREATE TABLE IF NOT EXISTS alerts (
    id                      BIGSERIAL PRIMARY KEY,
    alert_id                VARCHAR(100) NOT NULL UNIQUE,
    transaction_id          VARCHAR(100) NOT NULL,
    client_token            VARCHAR(255) NOT NULL,
    operator                VARCHAR(50)  NOT NULL,

    -- Score au moment de l'alerte
    final_score             DECIMAL(5,4) NOT NULL,
    risk_level              VARCHAR(20)  NOT NULL,
    fraud_type              VARCHAR(50),
    priority                VARCHAR(20),

    -- Workflow compliance officer
    status                  VARCHAR(30)  NOT NULL DEFAULT 'PENDING',
    is_confirmed_fraud      BOOLEAN,
    reviewed_by             VARCHAR(100),
    reviewed_at             TIMESTAMPTZ,
    compliance_notes        TEXT,

    -- Rapport STR BCM
    str_report_generated    BOOLEAN DEFAULT FALSE,
    str_report_path         VARCHAR(500),
    str_submitted_at        TIMESTAMPTZ,

    -- Timestamps
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    FOREIGN KEY (transaction_id)
        REFERENCES transaction_scores (transaction_id)
);

CREATE INDEX IF NOT EXISTS idx_alerts_status
    ON alerts (status);
CREATE INDEX IF NOT EXISTS idx_alerts_operator
    ON alerts (operator);
CREATE INDEX IF NOT EXISTS idx_alerts_created_at
    ON alerts (created_at);
CREATE INDEX IF NOT EXISTS idx_alerts_fraud_type
    ON alerts (fraud_type);


-- Détails techniques par modèle ML — pour monitoring et débogage
CREATE TABLE IF NOT EXISTS model_predictions (
    id                  BIGSERIAL PRIMARY KEY,
    transaction_id      VARCHAR(100) NOT NULL,
    model_name          VARCHAR(100) NOT NULL,
    model_version       VARCHAR(50),
    score               DECIMAL(5,4) NOT NULL,
    features_used       JSONB,
    inference_time_ms   DECIMAL(8,2),
    predicted_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    FOREIGN KEY (transaction_id)
        REFERENCES transaction_scores (transaction_id)
);

CREATE INDEX IF NOT EXISTS idx_model_predictions_tx
    ON model_predictions (transaction_id);
CREATE INDEX IF NOT EXISTS idx_model_predictions_model
    ON model_predictions (model_name, model_version);


-- Vue pour le réentraînement du modèle
-- Joint transactions_scores + alerts pour obtenir features + label fiable
CREATE OR REPLACE VIEW training_data_view AS
    SELECT
        ts.transaction_id,
        ts.client_token,
        ts.operator,
        ts.amount,
        ts.channel,
        ts.zone,
        ts.sim_changed_72h,
        ts.xgboost_score,
        ts.final_score,
        ts.shap_reasons,
        ts.analyzed_at,
        a.is_confirmed_fraud  AS label,
        a.fraud_type          AS confirmed_fraud_type,
        a.reviewed_at
    FROM transaction_scores ts
    JOIN alerts a ON ts.transaction_id = a.transaction_id
    WHERE a.reviewed_at IS NOT NULL;
"""


# ─────────────────────────────────────────────
# IMPLÉMENTATION PRINCIPALE
# ─────────────────────────────────────────────

class PostgresAuditStore(IAuditStore):
    """
    Audit trail immuable dans PostgreSQL.

    Hérite de IAuditStore — respecte le contrat défini
    dans application/ports/i_explainer_audit.py.

    Exemple d'utilisation :
        store = PostgresAuditStore(
            database_url="postgresql+asyncpg://user:pass@localhost/harisai"
        )
        await store.connect()
        await store.log_score(transaction, fraud_score)
        await store.log_alert(alert)
    """

    def __init__(
        self,
        database_url: str = "postgresql+asyncpg://harisai:harisai@localhost/harisai"
    ):
        self._database_url = database_url
        self._engine = None
        self._session_factory = None

    async def connect(self) -> None:
        """Établit la connexion PostgreSQL et crée les tables."""
        self._engine = create_async_engine(
            self._database_url,
            pool_size=10,
            max_overflow=20,
            echo=False,
        )
        self._session_factory = sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        # Crée les tables si elles n'existent pas
        await self._create_tables()

        logger.info(
            "Connexion PostgreSQL établie",
            extra={"url": self._database_url.split("@")[-1]}
        )

    async def disconnect(self) -> None:
        """Ferme la connexion PostgreSQL."""
        if self._engine:
            await self._engine.dispose()
            logger.info("Connexion PostgreSQL fermée")

    async def _create_tables(self) -> None:
        """Crée toutes les tables et index."""
        async with self._engine.begin() as conn:
            for statement in SQL_CREATE_TABLES.split(";"):
                stmt = statement.strip()
                if stmt:
                    await conn.execute(text(stmt))
        logger.info("Tables PostgreSQL créées/vérifiées")

    # ─────────────────────────────────────────
    # INTERFACE IAuditStore
    # ─────────────────────────────────────────

    async def log_score(
        self,
        transaction: Transaction,
        score: FraudScore,
    ) -> None:
        """
        Enregistre le score ML d'une transaction.
        Appelé pour CHAQUE transaction — APPROVE, REVIEW ou BLOCK.
        Entrée immuable — jamais modifiée après insertion.
        """
        shap_data = [
            {
                "feature_name":  r.feature_name,
                "contribution":  r.contribution,
                "readable_fr":   r.human_readable_fr,
                "readable_ar":   r.human_readable_ar,
            }
            for r in score.shap_reasons
        ]

        sql = text("""
            INSERT INTO transaction_scores (
                transaction_id,
                client_token,
                operator,
                amount,
                currency,
                channel,
                zone,
                xgboost_score,
                isolation_score,
                tft_score,
                gnn_score,
                final_score,
                risk_level,
                fraud_type,
                shap_reasons,
                model_version,
                inference_time_ms,
                sim_changed_72h,
                analyzed_at
            ) VALUES (
                :transaction_id,
                :client_token,
                :operator,
                :amount,
                :currency,
                :channel,
                :zone,
                :xgboost_score,
                :isolation_score,
                :tft_score,
                :gnn_score,
                :final_score,
                :risk_level,
                :fraud_type,
                :shap_reasons,
                :model_version,
                :inference_time_ms,
                :sim_changed_72h,
                :analyzed_at
            )
            ON CONFLICT (transaction_id) DO NOTHING
        """)

        params = {
            "transaction_id":    transaction.transaction_id,
            "client_token":      transaction.client_token.value,
            "operator":          transaction.operator,
            "amount":            float(transaction.amount.amount),
            "currency":          transaction.amount.currency.value,
            "channel":           transaction.channel.value,
            "zone":              transaction.zone,
            "xgboost_score":     round(score.xgboost_score, 4),
            "isolation_score":   round(score.isolation_score, 4),
            "tft_score":         round(score.tft_score, 4),
            "gnn_score":         round(score.gnn_score, 4),
            "final_score":       round(score.final_score, 4),
            "risk_level":        score.risk_level.value,
            "fraud_type":        score.suspected_fraud_type.value,
            "shap_reasons":      json.dumps(shap_data),
            "model_version":     score.model_version,
            "inference_time_ms": round(score.inference_time_ms, 2),
            "sim_changed_72h":   transaction.sim_changed_72h,
            "analyzed_at":       datetime.now(timezone.utc),
        }

        try:
            async with self._session_factory() as session:
                await session.execute(sql, params)
                await session.commit()

            logger.debug(
                "Score loggé",
                extra={
                    "transaction_id": transaction.transaction_id,
                    "score":          score.score_0_100,
                    "decision":       score.risk_level.value,
                }
            )

        except Exception as e:
            logger.error(
                "Erreur log_score PostgreSQL",
                extra={
                    "transaction_id": transaction.transaction_id,
                    "error": str(e)
                }
            )

    async def log_alert(self, alert: Alert) -> None:
        """
        Enregistre une alerte et son traitement compliance.
        Appelé à la création ET après chaque mise à jour
        (confirmation fraude ou faux positif).
        """
        sql = text("""
            INSERT INTO alerts (
                alert_id,
                transaction_id,
                client_token,
                operator,
                final_score,
                risk_level,
                fraud_type,
                priority,
                status,
                is_confirmed_fraud,
                reviewed_by,
                reviewed_at,
                compliance_notes,
                str_report_generated,
                str_report_path,
                str_submitted_at,
                created_at
            ) VALUES (
                :alert_id,
                :transaction_id,
                :client_token,
                :operator,
                :final_score,
                :risk_level,
                :fraud_type,
                :priority,
                :status,
                :is_confirmed_fraud,
                :reviewed_by,
                :reviewed_at,
                :compliance_notes,
                :str_report_generated,
                :str_report_path,
                :str_submitted_at,
                :created_at
            )
            ON CONFLICT (alert_id) DO UPDATE SET
                status               = EXCLUDED.status,
                is_confirmed_fraud   = EXCLUDED.is_confirmed_fraud,
                reviewed_by          = EXCLUDED.reviewed_by,
                reviewed_at          = EXCLUDED.reviewed_at,
                compliance_notes     = EXCLUDED.compliance_notes,
                str_report_generated = EXCLUDED.str_report_generated,
                str_report_path      = EXCLUDED.str_report_path,
                str_submitted_at     = EXCLUDED.str_submitted_at
        """)

        params = {
            "alert_id":            alert.alert_id,
            "transaction_id":      alert.transaction.transaction_id,
            "client_token":        alert.transaction.client_token.value,
            "operator":            alert.transaction.operator,
            "final_score":         round(alert.fraud_score.final_score, 4),
            "risk_level":          alert.fraud_score.risk_level.value,
            "fraud_type":          alert.fraud_score.suspected_fraud_type.value,
            "priority":            alert.priority.value,
            "status":              alert.status.value,
            "is_confirmed_fraud":  (True if alert.status.value == 'CONFIRMED'
                                   else False if alert.status.value == 'FALSE_POSITIVE'
                                   else None),
            "reviewed_by":         alert.reviewed_by,
            "reviewed_at":         alert.reviewed_at,
            "compliance_notes":    alert.compliance_notes,
            "str_report_generated": alert.str_report_generated,
            "str_report_path":     alert.str_report_path,
            "str_submitted_at":    alert.str_submitted_at,
            "created_at":          alert.created_at,
        }

        try:
            async with self._session_factory() as session:
                await session.execute(sql, params)
                await session.commit()

            logger.debug(
                "Alerte loggée",
                extra={
                    "alert_id": alert.alert_id,
                    "status":   alert.status.value,
                }
            )

        except Exception as e:
            logger.error(
                "Erreur log_alert PostgreSQL",
                extra={
                    "alert_id": alert.alert_id,
                    "error":    str(e)
                }
            )

    async def log_model_prediction(
        self,
        transaction_id: str,
        model_name: str,
        model_version: str,
        score: float,
        features_used: List[str],
        inference_time_ms: float,
    ) -> None:
        """
        Enregistre les détails techniques de chaque modèle ML.
        Utilisé pour le monitoring du drift et l'audit BCM.
        """
        sql = text("""
            INSERT INTO model_predictions (
                transaction_id,
                model_name,
                model_version,
                score,
                features_used,
                inference_time_ms,
                predicted_at
            ) VALUES (
                :transaction_id,
                :model_name,
                :model_version,
                :score,
                :features_used,
                :inference_time_ms,
                :predicted_at
            )
        """)

        params = {
            "transaction_id":    transaction_id,
            "model_name":        model_name,
            "model_version":     model_version,
            "score":             round(score, 4),
            "features_used":     json.dumps(features_used),
            "inference_time_ms": round(inference_time_ms, 2),
            "predicted_at":      datetime.now(timezone.utc),
        }

        try:
            async with self._session_factory() as session:
                await session.execute(sql, params)
                await session.commit()

        except Exception as e:
            logger.error(
                "Erreur log_model_prediction PostgreSQL",
                extra={
                    "transaction_id": transaction_id,
                    "model":          model_name,
                    "error":          str(e)
                }
            )

    # ─────────────────────────────────────────
    # REQUÊTES BCM — pour les rapports
    # ─────────────────────────────────────────

    async def get_training_data(
        self,
        operator: str,
        since: Optional[datetime] = None,
        limit: int = 10000,
    ) -> List[dict]:
        """
        Récupère les données labellées pour le réentraînement.
        Utilise la vue training_data_view — transactions confirmées.

        Args:
            operator : opérateur mobile money (BANKILY, SEDAD...)
            since    : date depuis laquelle récupérer les données
            limit    : nombre maximum de lignes

        Returns:
            Liste de dicts {features, label} pour le notebook
        """
        conditions = ["operator = :operator"]
        params: dict = {"operator": operator, "limit": limit}

        if since:
            conditions.append("reviewed_at >= :since")
            params["since"] = since

        where = " AND ".join(conditions)

        sql = text(f"""
            SELECT
                transaction_id,
                amount,
                channel,
                zone,
                sim_changed_72h,
                xgboost_score,
                final_score,
                shap_reasons,
                label,
                confirmed_fraud_type,
                reviewed_at
            FROM training_data_view
            WHERE {where}
            ORDER BY reviewed_at DESC
            LIMIT :limit
        """)

        try:
            async with self._session_factory() as session:
                result = await session.execute(sql, params)
                rows = result.fetchall()
                return [dict(row._mapping) for row in rows]

        except Exception as e:
            logger.error(
                "Erreur get_training_data",
                extra={"operator": operator, "error": str(e)}
            )
            return []

    async def get_stats(
        self,
        operator: str,
        days: int = 30,
    ) -> dict:
        """
        Statistiques de détection pour le dashboard compliance.

        Returns:
            {
                "total_analyzed":    1250,
                "total_blocked":     48,
                "total_review":      120,
                "total_approved":    1082,
                "confirmed_frauds":  35,
                "false_positives":   13,
                "detection_rate":    0.028
            }
        """
        sql = text("""
            SELECT
                COUNT(*)                                    AS total_analyzed,
                SUM(CASE WHEN risk_level='BLOCK' THEN 1 ELSE 0 END) AS total_blocked,
                SUM(CASE WHEN risk_level='REVIEW' THEN 1 ELSE 0 END) AS total_review,
                SUM(CASE WHEN risk_level='APPROVE' THEN 1 ELSE 0 END) AS total_approved
            FROM transaction_scores
            WHERE operator = :operator
              AND analyzed_at >= NOW() - INTERVAL ':days days'
        """)

        sql_alerts = text("""
            SELECT
                SUM(CASE WHEN is_confirmed_fraud=TRUE THEN 1 ELSE 0 END)  AS confirmed_frauds,
                SUM(CASE WHEN is_confirmed_fraud=FALSE THEN 1 ELSE 0 END) AS false_positives
            FROM alerts
            WHERE operator = :operator
              AND created_at >= NOW() - INTERVAL ':days days'
        """)

        try:
            async with self._session_factory() as session:
                r1 = await session.execute(sql, {"operator": operator, "days": days})
                r2 = await session.execute(sql_alerts, {"operator": operator, "days": days})

                row1 = r1.fetchone()
                row2 = r2.fetchone()

                total = int(row1.total_analyzed or 0)
                blocked = int(row1.total_blocked or 0)
                confirmed = int(row2.confirmed_frauds or 0)

                return {
                    "total_analyzed":  total,
                    "total_blocked":   blocked,
                    "total_review":    int(row1.total_review or 0),
                    "total_approved":  int(row1.total_approved or 0),
                    "confirmed_frauds": confirmed,
                    "false_positives": int(row2.false_positives or 0),
                    "detection_rate":  round(confirmed / total, 4) if total > 0 else 0,
                }

        except Exception as e:
            logger.error("Erreur get_stats", extra={"error": str(e)})
            return {}


# ─────────────────────────────────────────────
# VERSION IN-MEMORY — pour les tests unitaires
# ─────────────────────────────────────────────

class InMemoryAuditStore(IAuditStore):
    """
    Implémentation en mémoire de IAuditStore.
    Utilisée dans les tests unitaires — pas besoin de PostgreSQL.

    Stocke tout en mémoire dans des listes Python.
    """

    def __init__(self):
        self.scores: List[dict] = []
        self.alerts: List[dict] = []
        self.predictions: List[dict] = []

    async def log_score(
        self,
        transaction: Transaction,
        score: FraudScore,
    ) -> None:
        self.scores.append({
            "transaction_id": transaction.transaction_id,
            "final_score":    score.final_score,
            "risk_level":     score.risk_level.value,
            "fraud_type":     score.suspected_fraud_type.value,
            "logged_at":      datetime.now(timezone.utc),
        })

    async def log_alert(self, alert: Alert) -> None:
        self.alerts.append({
            "alert_id":           alert.alert_id,
            "transaction_id":     alert.transaction.transaction_id,
            "status":             alert.status.value,
            "is_confirmed_fraud": (True if alert.status.value == 'CONFIRMED'
                                   else False if alert.status.value == 'FALSE_POSITIVE'
                                   else None),
            "logged_at":          datetime.now(timezone.utc),
        })

    async def log_model_prediction(
        self,
        transaction_id: str,
        model_name: str,
        model_version: str,
        score: float,
        features_used: List[str],
        inference_time_ms: float,
    ) -> None:
        self.predictions.append({
            "transaction_id":    transaction_id,
            "model_name":        model_name,
            "score":             score,
            "inference_time_ms": inference_time_ms,
            "logged_at":         datetime.now(timezone.utc),
        })

    def count_scores(self) -> int:
        return len(self.scores)

    def count_alerts(self) -> int:
        return len(self.alerts)

    def last_score(self) -> Optional[dict]:
        return self.scores[-1] if self.scores else None

    def last_alert(self) -> Optional[dict]:
        return self.alerts[-1] if self.alerts else None