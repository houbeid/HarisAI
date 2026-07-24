using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace FraudDetection.Infrastructure.Migrations
{
    /// <inheritdoc />
    public partial class InitialCreate : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.EnsureSchema(
                name: "fraud_backend");

            migrationBuilder.CreateTable(
                name: "alerts",
                schema: "fraud_backend",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    alert_id = table.Column<string>(type: "character varying(50)", maxLength: 50, nullable: false),
                    transaction_id = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: false),
                    @operator = table.Column<string>(name: "operator", type: "character varying(50)", maxLength: 50, nullable: false),
                    score = table.Column<int>(type: "integer", nullable: false),
                    decision = table.Column<string>(type: "character varying(20)", maxLength: 20, nullable: false),
                    fraud_type = table.Column<string>(type: "character varying(50)", maxLength: 50, nullable: true),
                    xgboost_score = table.Column<double>(type: "double precision", nullable: true),
                    isolation_score = table.Column<double>(type: "double precision", nullable: true),
                    tft_score = table.Column<double>(type: "double precision", nullable: true),
                    gnn_score = table.Column<double>(type: "double precision", nullable: true),
                    status = table.Column<string>(type: "character varying(20)", maxLength: 20, nullable: false),
                    created_at = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    reviewed_at = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    reviewed_by = table.Column<string>(type: "character varying(255)", maxLength: 255, nullable: true),
                    review_note = table.Column<string>(type: "character varying(2000)", maxLength: 2000, nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("pk_alerts", x => x.id);
                });

            migrationBuilder.CreateTable(
                name: "pending_transactions",
                schema: "fraud_backend",
                columns: table => new
                {
                    id = table.Column<Guid>(type: "uuid", nullable: false),
                    transaction_id = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: false),
                    @operator = table.Column<string>(name: "operator", type: "character varying(50)", maxLength: 50, nullable: false),
                    client_token = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: false),
                    amount = table.Column<decimal>(type: "numeric(18,2)", precision: 18, scale: 2, nullable: false),
                    currency = table.Column<string>(type: "character varying(3)", maxLength: 3, nullable: false),
                    channel = table.Column<string>(type: "character varying(20)", maxLength: 20, nullable: false),
                    zone = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: false),
                    device_id = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: false),
                    sim_changed72h = table.Column<bool>(type: "boolean", nullable: false),
                    sim_changed_at = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    beneficiary_token = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: false),
                    beneficiary_is_merchant = table.Column<bool>(type: "boolean", nullable: false),
                    agent_id = table.Column<string>(type: "character varying(50)", maxLength: 50, nullable: true),
                    ussd_session = table.Column<bool>(type: "boolean", nullable: false),
                    timestamp = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    enqueued_at = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    attempt_count = table.Column<int>(type: "integer", nullable: false),
                    last_attempt_at = table.Column<DateTime>(type: "timestamp with time zone", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("pk_pending_transactions", x => x.id);
                });

            migrationBuilder.CreateTable(
                name: "str_reports",
                schema: "fraud_backend",
                columns: table => new
                {
                    report_id = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: false),
                    alert_id = table.Column<string>(type: "character varying(50)", maxLength: 50, nullable: false),
                    transaction_id = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: false),
                    @operator = table.Column<string>(name: "operator", type: "character varying(50)", maxLength: 50, nullable: false),
                    fraud_type = table.Column<string>(type: "character varying(50)", maxLength: 50, nullable: false),
                    risk_score = table.Column<int>(type: "integer", nullable: false),
                    decision = table.Column<string>(type: "character varying(20)", maxLength: 20, nullable: false),
                    confirmed_by = table.Column<string>(type: "character varying(255)", maxLength: 255, nullable: false),
                    agent_note = table.Column<string>(type: "character varying(2000)", maxLength: 2000, nullable: true),
                    generated_at = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    xgboost_score = table.Column<double>(type: "double precision", nullable: true),
                    isolation_score = table.Column<double>(type: "double precision", nullable: true),
                    tft_score = table.Column<double>(type: "double precision", nullable: true),
                    gnn_score = table.Column<double>(type: "double precision", nullable: true),
                    transmitted = table.Column<bool>(type: "boolean", nullable: false),
                    transmitted_at = table.Column<DateTime>(type: "timestamp with time zone", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("pk_str_reports", x => x.report_id);
                });

            migrationBuilder.CreateTable(
                name: "transactions",
                schema: "fraud_backend",
                columns: table => new
                {
                    transaction_id = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: false),
                    client_token = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: false),
                    amount = table.Column<decimal>(type: "numeric(18,2)", precision: 18, scale: 2, nullable: false),
                    currency = table.Column<string>(type: "character varying(3)", maxLength: 3, nullable: false),
                    channel = table.Column<string>(type: "character varying(20)", maxLength: 20, nullable: false),
                    zone = table.Column<string>(type: "character varying(100)", maxLength: 100, nullable: false),
                    @operator = table.Column<string>(name: "operator", type: "character varying(50)", maxLength: 50, nullable: false),
                    device_id = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: false),
                    sim_changed72h = table.Column<bool>(type: "boolean", nullable: false),
                    sim_changed_at = table.Column<DateTime>(type: "timestamp with time zone", nullable: true),
                    beneficiary_token = table.Column<string>(type: "character varying(128)", maxLength: 128, nullable: false),
                    beneficiary_is_merchant = table.Column<bool>(type: "boolean", nullable: false),
                    agent_id = table.Column<string>(type: "character varying(50)", maxLength: 50, nullable: true),
                    ussd_session = table.Column<bool>(type: "boolean", nullable: false),
                    timestamp = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    score = table.Column<int>(type: "integer", nullable: true),
                    decision = table.Column<string>(type: "character varying(20)", maxLength: 20, nullable: true),
                    fraud_type = table.Column<string>(type: "character varying(50)", maxLength: 50, nullable: true),
                    alert_id = table.Column<string>(type: "character varying(50)", maxLength: 50, nullable: true),
                    xgboost_score = table.Column<double>(type: "double precision", nullable: true),
                    isolation_score = table.Column<double>(type: "double precision", nullable: true),
                    tft_score = table.Column<double>(type: "double precision", nullable: true),
                    gnn_score = table.Column<double>(type: "double precision", nullable: true),
                    inference_time_ms = table.Column<double>(type: "double precision", nullable: true),
                    model_version = table.Column<string>(type: "character varying(20)", maxLength: 20, nullable: true),
                    is_default_review = table.Column<bool>(type: "boolean", nullable: false),
                    notification_status = table.Column<string>(type: "character varying(20)", maxLength: 20, nullable: false),
                    received_at = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    scored_at = table.Column<DateTime>(type: "timestamp with time zone", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("pk_transactions", x => x.transaction_id);
                });

            migrationBuilder.CreateIndex(
                name: "ix_alerts_alert_id",
                schema: "fraud_backend",
                table: "alerts",
                column: "alert_id",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "ix_alerts_operator_status_created_at",
                schema: "fraud_backend",
                table: "alerts",
                columns: new[] { "operator", "status", "created_at" });

            migrationBuilder.CreateIndex(
                name: "ix_alerts_transaction_id",
                schema: "fraud_backend",
                table: "alerts",
                column: "transaction_id",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "ix_pending_transactions_operator_enqueued_at",
                schema: "fraud_backend",
                table: "pending_transactions",
                columns: new[] { "operator", "enqueued_at" });

            migrationBuilder.CreateIndex(
                name: "ix_pending_transactions_transaction_id",
                schema: "fraud_backend",
                table: "pending_transactions",
                column: "transaction_id",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "ix_str_reports_alert_id",
                schema: "fraud_backend",
                table: "str_reports",
                column: "alert_id",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "ix_str_reports_operator_generated_at",
                schema: "fraud_backend",
                table: "str_reports",
                columns: new[] { "operator", "generated_at" });

            migrationBuilder.CreateIndex(
                name: "ix_str_reports_operator_transmitted",
                schema: "fraud_backend",
                table: "str_reports",
                columns: new[] { "operator", "transmitted" });

            migrationBuilder.CreateIndex(
                name: "ix_transactions_operator_decision",
                schema: "fraud_backend",
                table: "transactions",
                columns: new[] { "operator", "decision" });

            migrationBuilder.CreateIndex(
                name: "ix_transactions_operator_notification_status",
                schema: "fraud_backend",
                table: "transactions",
                columns: new[] { "operator", "notification_status" });

            migrationBuilder.CreateIndex(
                name: "ix_transactions_operator_received_at",
                schema: "fraud_backend",
                table: "transactions",
                columns: new[] { "operator", "received_at" });
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "alerts",
                schema: "fraud_backend");

            migrationBuilder.DropTable(
                name: "pending_transactions",
                schema: "fraud_backend");

            migrationBuilder.DropTable(
                name: "str_reports",
                schema: "fraud_backend");

            migrationBuilder.DropTable(
                name: "transactions",
                schema: "fraud_backend");
        }
    }
}
