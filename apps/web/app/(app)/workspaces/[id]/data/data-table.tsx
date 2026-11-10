import { columnIsNumeric, formatCell } from "@/lib/result-table";

export function DataTable({ columns, rows }: { columns: string[]; rows: unknown[][] }) {
  if (rows.length === 0) {
    return <p className="rounded border bg-white p-4 text-center text-sm text-gray-500">Tidak ada baris.</p>;
  }
  const numeric = columns.map((_, index) => columnIsNumeric(rows, index));
  return (
    <div className="max-h-96 overflow-auto rounded border bg-white">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-gray-100 text-left text-gray-700">
          <tr>
            {columns.map((name, index) => (
              <th key={name} className={`px-3 py-2 font-medium ${numeric[index] ? "text-right" : ""}`}>
                {name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex} className="border-t">
              {row.map((value, index) => (
                <td key={columns[index]} className={`px-3 py-1.5 ${numeric[index] ? "text-right tabular-nums" : ""}`}>
                  {formatCell(value)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
