using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace FraudDetection.Infrastructure.Migrations
{
    /// <inheritdoc />
    public partial class AddAlertAmount : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<decimal>(
                name: "amount_value",
                schema: "fraud_backend",
                table: "alerts",
                type: "numeric(18,2)",
                precision: 18,
                scale: 2,
                nullable: false,
                defaultValue: 0m);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "amount_value",
                schema: "fraud_backend",
                table: "alerts");
        }
    }
}
