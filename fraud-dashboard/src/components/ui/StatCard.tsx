interface StatCardProps {
  value: number | string;
  label: string;
}

/** Primitif purement présentationnel — la valeur est calculée en amont. */
export function StatCard({ value, label }: StatCardProps) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white px-6 py-4">
      <div className="text-3xl font-bold text-gray-900">{value}</div>
      <div className="text-sm text-gray-500">{label}</div>
    </div>
  );
}
