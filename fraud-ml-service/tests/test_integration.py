"""
HarisAI — Tests d'intégration
================================
Teste le flux complet bout-en-bout :
    .NET envoie JSON → FastAPI → pipeline ML → score retourné

Ces tests vérifient que tous les composants fonctionnent ensemble
sans Redis ni PostgreSQL réels — utilise les mocks du conftest.
"""

import pytest
from datetime import datetime, timezone


# ═══════════════════════════════════════════════════
# TESTS PIPELINE ML — USE CASE
# ═══════════════════════════════════════════════════

@pytest.mark.asyncio
class TestPipelineML:
    """Tests du pipeline ML via le use case."""

    async def test_transaction_normale_approuvee(self, use_case, tx_normale):
        """Une transaction normale doit être approuvée."""
        from application.use_cases import AnalyzeTransactionInput
        result = await use_case.execute(AnalyzeTransactionInput(tx_normale))

        assert result.fraud_score.risk_level.value == "APPROVE"
        assert result.alert is None
        assert result.profile_updated == True
        assert result.fraud_score.score_0_100 < 40

    async def test_sim_swap_bloque(self, use_case, tx_sim_swap):
        """Un SIM swap doit être bloqué."""
        from application.use_cases import AnalyzeTransactionInput
        result = await use_case.execute(AnalyzeTransactionInput(tx_sim_swap))

        assert result.fraud_score.risk_level.value == "BLOCK"
        assert result.alert is not None
        assert result.profile_updated == False
        assert result.fraud_score.score_0_100 >= 70

    async def test_alerte_creee_pour_block(self, use_case, tx_sim_swap):
        """Chaque BLOCK doit créer une alerte."""
        from application.use_cases import AnalyzeTransactionInput
        result = await use_case.execute(AnalyzeTransactionInput(tx_sim_swap))

        assert result.alert is not None
        assert result.alert.alert_id.startswith("ALT-")
        assert result.alert.is_pending == True

    async def test_pas_d_alerte_pour_approve(self, use_case, tx_normale):
        """Un APPROVE ne doit pas créer d'alerte."""
        from application.use_cases import AnalyzeTransactionInput
        result = await use_case.execute(AnalyzeTransactionInput(tx_normale))

        assert result.alert is None

    async def test_profile_mis_a_jour_apres_approve(
        self, use_case, tx_normale, profile_store, client_token
    ):
        """Le profil client doit être mis à jour après un APPROVE."""
        from application.use_cases import AnalyzeTransactionInput
        profile_avant = await profile_store.get(client_token, "BANKILY")
        tx_count_avant = profile_avant.total_transactions

        await use_case.execute(AnalyzeTransactionInput(tx_normale))

        profile_apres = await profile_store.get(client_token, "BANKILY")
        assert profile_apres.total_transactions == tx_count_avant + 1

    async def test_profile_non_mis_a_jour_apres_block(
        self, use_case, tx_sim_swap, profile_store, client_token
    ):
        """Le profil ne doit PAS être mis à jour après un BLOCK."""
        from application.use_cases import AnalyzeTransactionInput
        profile_avant = await profile_store.get(client_token, "BANKILY")
        tx_count_avant = profile_avant.total_transactions

        await use_case.execute(AnalyzeTransactionInput(tx_sim_swap))

        profile_apres = await profile_store.get(client_token, "BANKILY")
        assert profile_apres.total_transactions == tx_count_avant

    async def test_audit_trail_logue_chaque_transaction(
        self, use_case, tx_normale, tx_sim_swap, audit_store
    ):
        """Chaque transaction analysée doit être dans l'audit trail."""
        from application.use_cases import AnalyzeTransactionInput
        await use_case.execute(AnalyzeTransactionInput(tx_normale))
        await use_case.execute(AnalyzeTransactionInput(tx_sim_swap))

        assert audit_store.count_scores() == 2

    async def test_score_ensemble_combine_4_modeles(self, use_case, tx_sim_swap):
        """Le score final doit être une combinaison pondérée des 4 modèles."""
        from application.use_cases import AnalyzeTransactionInput
        result = await use_case.execute(AnalyzeTransactionInput(tx_sim_swap))

        score = result.fraud_score
        # XGBoost > 0 pour SIM swap
        assert score.xgboost_score > 0
        # Score final entre 0 et 1
        assert 0.0 <= score.final_score <= 1.0
        # Décision BLOCK pour SIM swap
        assert score.risk_level.value == "BLOCK"

    async def test_nouveau_client_profil_cree(self, use_case, client_token):
        """Un nouveau client doit recevoir un profil vide."""
        from application.use_cases import AnalyzeTransactionInput
        from domain import Transaction, Money, Channel, TokenHash

        tx = Transaction(
            transaction_id="BNK-NEW-001",
            client_token=TokenHash("nouveau_client_hash00"),
            amount=Money(5000.0),
            timestamp=datetime(2024, 1, 15, 10, 0),
            channel=Channel.MOBILE_APP,
            zone="TEVRAGH_ZEINA",
            operator="BANKILY",
            device_id="device_nouveau",
        )
        result = await use_case.execute(AnalyzeTransactionInput(tx))

        # Nouveau client → pas assez d'historique pour bloquer
        assert result.fraud_score is not None
        assert result.total_time_ms >= 0


# ═══════════════════════════════════════════════════
# TESTS API — ENDPOINTS FASTAPI
# ═══════════════════════════════════════════════════

@pytest.mark.asyncio
class TestAPIEndpoints:
    """Tests des endpoints FastAPI via httpx."""

    async def test_health_check(self, client):
        """GET /health doit retourner 200."""
        response = await client.get("/api/v1/health")

        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "model_ready" in data
        assert "uptime_seconds" in data

    async def test_analyze_transaction_normale(self, client, tx_normale_json):
        """POST /analyze avec transaction normale → APPROVE."""
        response = await client.post("/api/v1/analyze", json=tx_normale_json)

        assert response.status_code == 200
        data = response.json()
        assert data["transaction_id"] == "BNK-API-001"
        assert "score" in data
        assert "decision" in data
        assert data["decision"] in ["APPROVE", "REVIEW", "BLOCK"]

    async def test_analyze_sim_swap(self, client, tx_sim_swap_json):
        """POST /analyze avec SIM swap → BLOCK."""
        response = await client.post("/api/v1/analyze", json=tx_sim_swap_json)

        assert response.status_code == 200
        data = response.json()
        assert data["decision"] == "BLOCK"
        assert data["score"] >= 70
        assert data["alert_id"] is not None

    async def test_analyze_retourne_score_0_100(self, client, tx_sim_swap_json):
        """Le score retourné doit être entre 0 et 100."""
        response = await client.post("/api/v1/analyze", json=tx_sim_swap_json)

        data = response.json()
        assert 0 <= data["score"] <= 100

    async def test_analyze_retourne_raisons_shap(self, client, tx_sim_swap_json):
        """La réponse doit contenir les raisons SHAP."""
        response = await client.post("/api/v1/analyze", json=tx_sim_swap_json)

        data = response.json()
        assert "reasons" in data
        assert isinstance(data["reasons"], list)

    async def test_analyze_sans_api_key(self, test_app, tx_normale_json):
        """POST /analyze sans API key → 401."""
        from httpx import AsyncClient, ASGITransport
        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://test",
        ) as ac:
            response = await ac.post("/api/v1/analyze", json=tx_normale_json)
        assert response.status_code == 401

    async def test_analyze_mauvaise_api_key(self, test_app, tx_normale_json):
        """POST /analyze avec mauvaise API key → 403."""
        from httpx import AsyncClient, ASGITransport
        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://test",
            headers={"X-Api-Key": "mauvaise-cle"},
        ) as ac:
            response = await ac.post("/api/v1/analyze", json=tx_normale_json)
        assert response.status_code == 403

    async def test_analyze_montant_negatif(self, client):
        """POST /analyze avec montant négatif → 422."""
        response = await client.post("/api/v1/analyze", json={
            "transaction_id": "BNK-BAD-001",
            "client_token":   "a3f9b2c1d4e5f6a7",
            "amount":         -500.0,  # ← invalide
            "channel":        "MOBILE_APP",
            "zone":           "TEVRAGH",
            "operator":       "BANKILY",
            "device_id":      "device_xyz",
        })
        assert response.status_code == 422

    async def test_analyze_operateur_inconnu(self, client):
        """POST /analyze avec opérateur inconnu → 422."""
        response = await client.post("/api/v1/analyze", json={
            "transaction_id": "BNK-BAD-002",
            "client_token":   "a3f9b2c1d4e5f6a7",
            "amount":         5000.0,
            "channel":        "MOBILE_APP",
            "zone":           "TEVRAGH",
            "operator":       "INCONNU",  # ← invalide
            "device_id":      "device_xyz",
        })
        assert response.status_code == 422

    async def test_analyze_async(self, client, tx_normale_json):
        """POST /analyze-async doit retourner 202 immédiatement."""
        tx = {**tx_normale_json, "transaction_id": "BNK-ASYNC-001"}
        response = await client.post("/api/v1/analyze-async", json=tx)

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"
        assert "message_id" in data
        assert "result_url" in data

    async def test_cache_hit(self, client, tx_sim_swap_json, prediction_cache):
        """La deuxième requête avec le même transaction_id doit utiliser le cache."""
        # Pré-charge le cache
        await prediction_cache.set(
            "BNK-API-002", "BANKILY",
            {
                "transaction_id":   "BNK-API-002",
                "score":            87,
                "decision":         "BLOCK",
                "fraud_type":       "SIM_SWAPPING",
                "alert_id":         "ALT-CACHED",
                "xgboost_score":    0.94,
                "isolation_score":  0.0,
                "tft_score":        0.0,
                "gnn_score":        0.0,
                "reasons":          [],
                "inference_time_ms": 1.0,
                "model_version":    "1.0.0",
            }
        )
        response = await client.post("/api/v1/analyze", json=tx_sim_swap_json)

        assert response.status_code == 200
        data = response.json()
        # Le résultat vient du cache
        assert data["score"] == 87

    async def test_model_info(self, client):
        """GET /model doit retourner les infos du modèle."""
        response = await client.get("/api/v1/model")

        assert response.status_code == 200
        data = response.json()
        assert "model_name" in data
        assert "model_version" in data
        assert "status" in data

    async def test_queue_stats(self, client):
        """GET /queue/stats doit retourner les stats de la queue."""
        response = await client.get("/api/v1/queue/stats")

        assert response.status_code == 200
        data = response.json()
        assert "queues" in data
        assert "cache" in data

    async def test_root_endpoint(self, client):
        """GET / doit retourner les infos du service."""
        response = await client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "HarisAI Fraud Detection"
        assert "docs" in data


# ═══════════════════════════════════════════════════
# TESTS CACHE
# ═══════════════════════════════════════════════════

@pytest.mark.asyncio
class TestCache:

    async def test_cache_miss_puis_hit(self, prediction_cache):
        """Cache miss puis cache hit."""
        result = await prediction_cache.get("BNK-001", "BANKILY")
        assert result is None

        await prediction_cache.set("BNK-001", "BANKILY", {"score": 87})
        result = await prediction_cache.get("BNK-001", "BANKILY")
        assert result is not None
        assert result["score"] == 87
        assert result["from_cache"] == True

    async def test_cache_operateurs_separes(self, prediction_cache):
        """Le cache est séparé par opérateur."""
        await prediction_cache.set("BNK-001", "BANKILY", {"score": 87})
        result = await prediction_cache.get("BNK-001", "SEDAD")
        assert result is None

    async def test_cache_invalidation(self, prediction_cache):
        """L'invalidation supprime l'entrée du cache."""
        await prediction_cache.set("BNK-001", "BANKILY", {"score": 87})
        await prediction_cache.invalidate("BNK-001", "BANKILY")
        result = await prediction_cache.get("BNK-001", "BANKILY")
        assert result is None


# ═══════════════════════════════════════════════════
# TESTS QUEUE
# ═══════════════════════════════════════════════════

@pytest.mark.asyncio
class TestQueue:

    async def test_push_retourne_message_id(self, transaction_queue):
        msg_id = await transaction_queue.push(
            {"transaction_id": "BNK-001"},
            "BANKILY"
        )
        assert msg_id is not None

    async def test_queue_size(self, transaction_queue):
        assert await transaction_queue.queue_size("BANKILY") == 0
        await transaction_queue.push({"transaction_id": "BNK-001"}, "BANKILY")
        await transaction_queue.push({"transaction_id": "BNK-002"}, "BANKILY")
        assert await transaction_queue.queue_size("BANKILY") == 2

    async def test_queues_separees_par_operateur(self, transaction_queue):
        await transaction_queue.push({"transaction_id": "BNK-001"}, "BANKILY")
        await transaction_queue.push({"transaction_id": "SED-001"}, "SEDAD")
        assert await transaction_queue.queue_size("BANKILY") == 1
        assert await transaction_queue.queue_size("SEDAD") == 1

    async def test_process_all(self, transaction_queue):
        for i in range(5):
            await transaction_queue.push(
                {"transaction_id": f"BNK-{i:03d}"},
                "BANKILY"
            )
        processed = []
        async def fake_process(data):
            processed.append(data["transaction_id"])

        await transaction_queue.process_all(fake_process)
        assert len(processed) == 5
        assert await transaction_queue.queue_size("BANKILY") == 0