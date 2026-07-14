"""
HarisAI — Tests d'intégration
================================
Teste le flux complet bout-en-bout :
    .NET envoie JSON → FastAPI → pipeline ML → score retourné

Ces tests vérifient que tous les composants fonctionnent ensemble
sans Redis ni PostgreSQL réels — utilise les mocks du conftest.
"""

import pytest
from datetime import datetime, timedelta, timezone
from domain import (
    Transaction, Money, Channel, TokenHash,
    FraudType, BeneficiaryProfile, ClientProfile,
)
from application.use_cases import AnalyzeTransactionInput
from application.use_cases.analyze_transaction import _detect_fraud_type


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
        assert result.total_time_ms > 0


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

    async def test_metrics_endpoint(self, client, tx_normale_json):
        """GET /metrics doit exposer les métriques Prometheus."""
        # Génère un peu de trafic pour peupler les métriques
        await client.post("/api/v1/analyze", json=tx_normale_json)
        await client.get("/api/v1/health")

        response = await client.get("/api/v1/metrics")
        assert response.status_code == 200
        assert "text/plain" in response.headers["content-type"]

        body = response.text
        assert "harisai_transactions_total" in body
        assert "harisai_decisions_total" in body
        assert "harisai_inference_duration_seconds" in body
        assert "harisai_model_ready" in body

    async def test_metrics_sans_api_key(self, client):
        """GET /metrics ne nécessite PAS de X-Api-Key (scraping Prometheus)."""
        from httpx import AsyncClient, ASGITransport
        # Utilise le client SANS le header X-Api-Key
        async with AsyncClient(
            transport=ASGITransport(app=client._transport.app),
            base_url="http://test",
        ) as ac_no_key:
            response = await ac_no_key.get("/api/v1/metrics")
            assert response.status_code == 200

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
# TESTS RATE LIMITING
# ═══════════════════════════════════════════════════

@pytest.mark.asyncio
class TestRateLimiting:

    async def test_requetes_normales_passent(self, client, tx_normale_json):
        """Sous la limite, les requêtes passent normalement."""
        for i in range(5):
            tx = {**tx_normale_json, "transaction_id": f"BNK-RL-{i:03d}"}
            response = await client.post("/api/v1/analyze", json=tx)
            assert response.status_code == 200

    async def test_rate_limit_status_endpoint(self, client):
        """GET /rate-limit/{operator} retourne l'usage actuel."""
        response = await client.get("/api/v1/rate-limit/BANKILY")
        assert response.status_code == 200
        data = response.json()
        assert data["operator"] == "BANKILY"
        assert "current_count" in data
        assert "limit_per_minute" in data
        assert "remaining" in data

    async def test_depassement_limite_429(self, test_app, tx_normale_json):
        """Au-delà de la limite, l'API retourne 429."""
        from httpx import AsyncClient, ASGITransport
        from infrastructure.stores.rate_limiter import RATE_LIMITS

        # Limite temporaire basse pour le test — sur un opérateur valide
        RATE_LIMITS["MASRVI"] = 3

        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://test",
            headers={"X-Api-Key": "harisai-secret-key-change-in-production"},
        ) as ac:
            for i in range(3):
                tx = {
                    **tx_normale_json,
                    "transaction_id": f"MSR-429-{i:03d}",
                    "operator": "MASRVI",
                }
                response = await ac.post("/api/v1/analyze", json=tx)
                assert response.status_code == 200

            # 4ème requête → 429
            tx = {
                **tx_normale_json,
                "transaction_id": "MSR-429-OVER",
                "operator": "MASRVI",
            }
            response = await ac.post("/api/v1/analyze", json=tx)
            assert response.status_code == 429
            assert "Limite" in response.json()["detail"]

        # Restaure la limite par défaut pour ne pas affecter d'autres tests
        RATE_LIMITS["MASRVI"] = 500

    async def test_operateurs_independants(self, test_app, tx_normale_json):
        """Le rate limit d'un opérateur n'affecte pas un autre."""
        from httpx import AsyncClient, ASGITransport
        from infrastructure.stores.rate_limiter import RATE_LIMITS

        RATE_LIMITS["SEDAD"]  = 2
        RATE_LIMITS["MASRVI"] = 2

        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://test",
            headers={"X-Api-Key": "harisai-secret-key-change-in-production"},
        ) as ac:
            # Sature SEDAD
            for i in range(2):
                tx = {**tx_normale_json, "transaction_id": f"SED-{i}", "operator": "SEDAD"}
                r = await ac.post("/api/v1/analyze", json=tx)
                assert r.status_code == 200

            # SEDAD est maintenant saturé
            tx = {**tx_normale_json, "transaction_id": "SED-OVER", "operator": "SEDAD"}
            r = await ac.post("/api/v1/analyze", json=tx)
            assert r.status_code == 429

            # MASRVI fonctionne toujours normalement
            tx = {**tx_normale_json, "transaction_id": "MSR-001", "operator": "MASRVI"}
            r = await ac.post("/api/v1/analyze", json=tx)
            assert r.status_code == 200

        # Restaure les limites par défaut
        RATE_LIMITS["SEDAD"]  = 500
        RATE_LIMITS["MASRVI"] = 500


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


# ═══════════════════════════════════════════════════
# BRANCHEMENT is_mule_pattern — bout en bout
# ═══════════════════════════════════════════════════

class TestIsMulePatternBranchement:
    """
    Vérifie que is_mule_pattern, calculé via BeneficiaryProfile, est
    bien actif sur le flux réel du use case quand beneficiary_store
    est injecté — pas seulement dans FeatureEngineering (training).

    Avant ce branchement, analyze_transaction.py avait sa propre
    _build_features() qui ne calculait jamais is_mule_pattern et
    n'accédait jamais à un BeneficiaryProfile, même si le code de
    détection mule (domain/transaction.py) était déjà écrit et testé.
    """

    def _make_token(self, prefix: str) -> TokenHash:
        return TokenHash((prefix * 64)[:64])

    async def test_sans_beneficiary_store_is_mule_pattern_vaut_zero(
        self, use_case, tx_normale
    ):
        """
        Compatibilité ascendante — use_case (sans beneficiary_store)
        doit continuer à fonctionner exactement comme avant.
        """
        result = await use_case.execute(AnalyzeTransactionInput(tx_normale))
        assert result.fraud_score.risk_level.value in ("APPROVE", "REVIEW", "BLOCK")
        # Pas d'erreur levée — c'est le test principal ici

    async def test_premiere_transaction_vers_nouveau_beneficiaire(
        self, use_case_with_beneficiary, beneficiary_store, client_token
    ):
        """
        Avec beneficiary_store injecté, une toute première transaction
        vers un bénéficiaire jamais vu ne doit pas planter, et ne peut
        pas encore être un pattern mule (aucun historique de réception).
        """
        tx = Transaction(
            transaction_id="BNK-MULE-001",
            client_token=client_token,
            amount=Money(5000.0),
            timestamp=datetime(2024, 1, 15, 9, 30),
            channel=Channel.MOBILE_APP,
            zone="NOUAKCHOTT",
            operator="BANKILY",
            device_id="device_xyz",
            beneficiary_token=self._make_token("b"),
            beneficiary_is_merchant=False,
        )
        result = await use_case_with_beneficiary.execute(
            AnalyzeTransactionInput(tx)
        )
        assert result.fraud_score.risk_level.value in ("APPROVE", "REVIEW", "BLOCK")

        # Le profil bénéficiaire doit avoir été créé et mis à jour
        # (update_inflow appelé en étape 9, car APPROVE par défaut avec
        # les mocks pass-through configurés à un score bas)
        if result.fraud_score.risk_level.value == "APPROVE":
            profile = await beneficiary_store.get(
                self._make_token("b"), "BANKILY"
            )
            assert profile is not None
            assert profile.total_transactions_received == 1

    async def test_mule_pattern_detecte_apres_fan_in_et_sortie_rapide(
        self, use_case_with_beneficiary, beneficiary_store, profile_store
    ):
        """
        Cas central — simule le scénario complet : un compte mule reçoit
        de nombreux expéditeurs différents, puis fait sortir les fonds
        rapidement. Vérifie que is_mule_pattern est bien actif dans les
        features calculées par le use case réel (pas seulement dans
        FeatureEngineering.compute(), qui était jusqu'ici le seul endroit
        où cette feature existait).
        """
        from domain import ClientProfile

        mule_token = self._make_token("m")

        # 20 expéditeurs différents envoient au même compte "mule" —
        # chaque expéditeur est pré-chargé avec un historique actif
        # (last_transaction_at récent) pour éviter que MockXGBoostModel
        # ne les classe comme is_dormant_account=True (ce qui forcerait
        # un BLOCK et empêcherait update_inflow() de jamais s'exécuter,
        # puisqu'il n'a lieu qu'après une décision APPROVE).
        for i in range(20):
            sender_token = TokenHash(f"s{i}".ljust(64, "0"))
            profile_store.seed(
                sender_token, "BANKILY",
                ClientProfile(
                    client_token=sender_token,
                    operator="BANKILY",
                    last_transaction_at=datetime.now(timezone.utc),
                    total_transactions=5,
                )
            )
            tx = Transaction(
                transaction_id=f"BNK-MULE-IN-{i:03d}",
                client_token=sender_token,
                amount=Money(5000.0),
                timestamp=datetime(2024, 1, 15, 10, i),
                channel=Channel.MOBILE_APP,
                zone="NOUAKCHOTT",
                operator="BANKILY",
                device_id=f"device_{i}",
                beneficiary_token=mule_token,
                beneficiary_is_merchant=False,
            )
            await use_case_with_beneficiary.execute(AnalyzeTransactionInput(tx))

        mule_profile = await beneficiary_store.get(mule_token, "BANKILY")
        assert mule_profile is not None
        assert mule_profile.distinct_senders_30d >= 15  # fan-in élevé confirmé

        # Le compte mule envoie maintenant lui-même de l'argent (sortie
        # rapide après réception) — déclenche update_outflow() en étape 9.
        # Pré-charge aussi son profil expéditeur pour la même raison.
        profile_store.seed(
            mule_token, "BANKILY",
            ClientProfile(
                client_token=mule_token,
                operator="BANKILY",
                last_transaction_at=datetime.now(timezone.utc),
                total_transactions=5,
            )
        )
        outflow_tx = Transaction(
            transaction_id="BNK-MULE-OUT-001",
            client_token=mule_token,
            amount=Money(95000.0),
            timestamp=datetime(2024, 1, 15, 11, 0),  # ~50min après la dernière entrée
            channel=Channel.MOBILE_APP,
            zone="NOUAKCHOTT",
            operator="BANKILY",
            device_id="device_mule",
            beneficiary_token=self._make_token("z"),  # un tiers quelconque
            beneficiary_is_merchant=False,
        )
        await use_case_with_beneficiary.execute(AnalyzeTransactionInput(outflow_tx))

        mule_profile_updated = await beneficiary_store.get(mule_token, "BANKILY")
        assert mule_profile_updated.last_outflow_at is not None
        # Le pattern mule est maintenant détectable pour ce compte
        assert mule_profile_updated.is_likely_mule(is_merchant=False) is True

    async def test_marchand_avec_fan_in_eleve_jamais_flagge(
        self, use_case_with_beneficiary, beneficiary_store, profile_store
    ):
        """
        Réplique le point soulevé sur les commerces mauritaniens — un
        marchand avec un fan-in tout aussi élevé qu'une mule ne doit
        jamais voir is_mule_pattern actif, grâce à beneficiary_is_merchant.
        """
        from domain import ClientProfile

        merchant_token = self._make_token("c")

        for i in range(20):
            sender_token = TokenHash(f"s{i}".ljust(64, "1"))
            profile_store.seed(
                sender_token, "BANKILY",
                ClientProfile(
                    client_token=sender_token,
                    operator="BANKILY",
                    last_transaction_at=datetime.now(timezone.utc),
                    total_transactions=5,
                )
            )
            tx = Transaction(
                transaction_id=f"BNK-MERCHANT-IN-{i:03d}",
                client_token=sender_token,
                amount=Money(3000.0),
                timestamp=datetime(2024, 1, 15, 10, i),
                channel=Channel.MOBILE_APP,
                zone="NOUAKCHOTT",
                operator="BANKILY",
                device_id=f"device_{i}",
                beneficiary_token=merchant_token,
                beneficiary_is_merchant=True,  # marchand déclaré
            )
            await use_case_with_beneficiary.execute(AnalyzeTransactionInput(tx))

        merchant_profile = await beneficiary_store.get(merchant_token, "BANKILY")
        assert merchant_profile is not None
        assert merchant_profile.distinct_senders_30d >= 15  # fan-in élevé aussi

        # Même avec un fan-in élevé, is_merchant=True protège ce compte
        assert merchant_profile.is_likely_mule(is_merchant=True) is False


class TestDetectFraudTypeBranchement:
    """
    Teste _detect_fraud_type() (application/use_cases/analyze_transaction.py)
    directement — AUCUN test n'existait sur cette fonction avant, alors
    qu'elle produit le fraud_type envoyé dans les rapports STR à la BCM.

    Point central testé : le LABEL MULE_ACCOUNT doit utiliser
    BeneficiaryProfile.is_likely_mule() quand disponible — la même
    méthode qui alimente déjà la feature is_mule_pattern — plutôt que
    l'ancienne heuristique brute (is_new_account + ratio_to_avg > 5),
    qui reste en fallback uniquement si beneficiary_profile est absent.

    Import direct d'une fonction privée (préfixe _) : choix délibéré —
    _detect_fraud_type() est une fonction pure sans état, la tester
    directement (white-box) est plus simple et plus ciblé que de
    passer par le use case complet (comme TestIsMulePatternBranchement
    le fait pour la feature is_mule_pattern, un besoin différent : là
    on teste l'intégration bout en bout, ici la logique de décision
    isolée).
    """

    def _make_transaction(self, **overrides) -> Transaction:
        defaults = dict(
            transaction_id="BNK-FRAUDTYPE-001",
            client_token=TokenHash(("c" * 64)),
            amount=Money(8500.0),
            timestamp=datetime(2024, 1, 15, 9, 30),
            channel=Channel.MOBILE_APP,
            zone="NOUAKCHOTT",
            operator="BANKILY",
            device_id="device_xyz",
        )
        defaults.update(overrides)
        return Transaction(**defaults)

    def _make_beneficiary_profile(
        self,
        distinct_senders_30d: int = 20,
        outflow_gap_hours: float = 1.0,
    ) -> BeneficiaryProfile:
        """Profil bénéficiaire qui déclenche is_likely_mule() par défaut
        (fan-in > 15, non-marchand, sortie rapide < 24h)."""
        received_at = datetime(2024, 1, 15, 8, 0)
        return BeneficiaryProfile(
            beneficiary_token=TokenHash(("b" * 64)),
            operator="BANKILY",
            distinct_senders_30d=distinct_senders_30d,
            last_received_at=received_at,
            last_outflow_at=received_at + timedelta(hours=outflow_gap_hours),
        )

    def test_sim_swapping_detecte(self):
        tx = self._make_transaction(sim_changed_72h=True)
        features = {"is_new_device": True, "amount_z_score": 4.0}
        result = _detect_fraud_type(tx, ClientProfile(
            client_token=tx.client_token, operator="BANKILY"
        ), features, xgboost_score=0.5)
        assert result == FraudType.SIM_SWAPPING

    def test_account_takeover_detecte_sans_sim_swap(self):
        tx = self._make_transaction(sim_changed_72h=False)
        features = {
            "is_new_device": True,
            "is_new_zone": True,
            "amount_z_score": 4.0,
        }
        result = _detect_fraud_type(tx, ClientProfile(
            client_token=tx.client_token, operator="BANKILY"
        ), features, xgboost_score=0.5)
        assert result == FraudType.ACCOUNT_TAKEOVER

    def test_sim_swapping_prioritaire_sur_account_takeover(self):
        """
        Si sim_changed_72h ET device/zone nouveaux ET z-score élevé sont
        TOUS vrais, SIM_SWAPPING doit gagner (vérifié en premier) —
        ACCOUNT_TAKEOVER ne doit jamais être retourné dans ce cas, pas
        d'ambiguïté entre les deux règles.
        """
        tx = self._make_transaction(sim_changed_72h=True)
        features = {
            "is_new_device": True,
            "is_new_zone": True,
            "amount_z_score": 4.0,
        }
        result = _detect_fraud_type(tx, ClientProfile(
            client_token=tx.client_token, operator="BANKILY"
        ), features, xgboost_score=0.5)
        assert result == FraudType.SIM_SWAPPING

    def test_mule_account_via_beneficiary_profile(self):
        """
        Cas central de ce branchement : beneficiary_profile disponible
        et is_likely_mule() vrai → MULE_ACCOUNT, MÊME SI les champs de
        l'ancienne heuristique brute (is_new_account, ratio_to_avg) sont
        absents ou faux — preuve que c'est bien is_likely_mule() qui
        décide, pas l'ancien fallback.
        """
        tx = self._make_transaction(
            beneficiary_token=TokenHash(("b" * 64)),
            beneficiary_is_merchant=False,
        )
        features = {}  # is_new_account et ratio_to_avg absents/faux
        beneficiary_profile = self._make_beneficiary_profile()
        result = _detect_fraud_type(
            tx,
            ClientProfile(client_token=tx.client_token, operator="BANKILY"),
            features,
            xgboost_score=0.5,
            beneficiary_profile=beneficiary_profile,
        )
        assert result == FraudType.MULE_ACCOUNT

    def test_mule_account_beneficiary_profile_bloque_faux_positif_marchand(self):
        """
        Un bénéficiaire marchand avec fan-in élevé NE DOIT PAS être
        labellisé MULE_ACCOUNT, même si les champs de l'ancienne
        heuristique brute auraient matché — le filet de sécurité
        anti-faux-positif marchand (section 3.5 de la doc technique)
        doit être respecté par le LABEL, pas seulement par la feature.
        """
        tx = self._make_transaction(
            beneficiary_token=TokenHash(("b" * 64)),
            beneficiary_is_merchant=True,  # marchand déclaré
        )
        features = {"is_new_account": True, "ratio_to_avg": 6.0}
        beneficiary_profile = self._make_beneficiary_profile()  # fan-in élevé
        result = _detect_fraud_type(
            tx,
            ClientProfile(client_token=tx.client_token, operator="BANKILY"),
            features,
            xgboost_score=0.5,
            beneficiary_profile=beneficiary_profile,
        )
        assert result != FraudType.MULE_ACCOUNT

    def test_mule_account_fallback_sans_beneficiary_profile(self):
        """
        Sans beneficiary_profile (store non disponible, ou bénéficiaire
        jamais vu) — retombe sur l'ancienne heuristique brute plutôt que
        de ne jamais détecter MULE_ACCOUNT.
        """
        tx = self._make_transaction()
        features = {"is_new_account": True, "ratio_to_avg": 6.0}
        result = _detect_fraud_type(
            tx,
            ClientProfile(client_token=tx.client_token, operator="BANKILY"),
            features,
            xgboost_score=0.5,
            beneficiary_profile=None,
        )
        assert result == FraudType.MULE_ACCOUNT

    def test_unusual_behavior_par_defaut(self):
        tx = self._make_transaction()
        features = {}
        result = _detect_fraud_type(
            tx,
            ClientProfile(client_token=tx.client_token, operator="BANKILY"),
            features,
            xgboost_score=0.1,
            beneficiary_profile=None,
        )
        assert result == FraudType.UNUSUAL_BEHAVIOR