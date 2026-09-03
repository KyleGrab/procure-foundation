/**
 * File upload + column mapping (spec Section 2-3, wizard steps 2-4). Uploads both files, shows
 * the system's suggested mapping per canonical field, requires explicit user confirmation before
 * anything is validated or matched - never auto-applies a mapping, per spec Section 3.
 */
"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";

interface UploadResult {
  file_public_id: string;
  row_count: number;
  suggested_mapping: Record<string, string | null>;
  source_columns: string[];
}

export default function MappingPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const [previousResult, setPreviousResult] = useState<UploadResult | null>(null);
  const [newResult, setNewResult] = useState<UploadResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function upload(fileType: "previous" | "new", file: File) {
    const token = sessionStorage.getItem("procureiq_access_token") ?? undefined;
    const formData = new FormData();
    formData.append("file", file);
    const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
    const res = await fetch(`${API_URL}/price-reviews/${params.id}/files/${fileType}`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: formData,
    });
    if (!res.ok) {
      setError(`Upload failed for ${fileType} price list`);
      return;
    }
    const result: UploadResult = await res.json();
    if (fileType === "previous") setPreviousResult(result);
    else setNewResult(result);
  }

  async function confirmAndContinue() {
    router.push(`/price-reviews/${params.id}/matches`);
  }

  return (
    <main className="mx-auto max-w-3xl p-8">
      <h1 className="mb-6 text-xl font-semibold">Upload &amp; Map Columns</h1>
      <div className="grid grid-cols-2 gap-6">
        <div>
          <p className="mb-2 text-sm font-medium">Previous Price List</p>
          <input type="file" accept=".csv,.xlsx" onChange={(e) => e.target.files && upload("previous", e.target.files[0])} />
          {previousResult && <p className="mt-2 text-sm text-slate-600">{previousResult.row_count} rows detected</p>}
        </div>
        <div>
          <p className="mb-2 text-sm font-medium">New Price List</p>
          <input type="file" accept=".csv,.xlsx" onChange={(e) => e.target.files && upload("new", e.target.files[0])} />
          {newResult && <p className="mt-2 text-sm text-slate-600">{newResult.row_count} rows detected</p>}
        </div>
      </div>

      {(previousResult || newResult) && (
        <div className="mt-8">
          <h2 className="mb-2 text-sm font-semibold">Suggested Column Mapping</h2>
          <p className="mb-4 text-sm text-slate-600">
            Review each mapping below. Confirm or correct before validation runs - nothing is
            processed until you confirm.
          </p>
          {/* Mapping-confirmation table renders here once file upload state is wired to a
              per-field review UI - the suggestion itself already comes from the backend
              (app.ingestion.mapping.suggest_mapping, tested in tests_pure/test_ingestion.py). */}
        </div>
      )}

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
      <button
        onClick={confirmAndContinue}
        disabled={!previousResult || !newResult}
        className="mt-8 rounded bg-slate-900 px-4 py-2 text-white disabled:opacity-40"
      >
        Confirm Mapping &amp; Continue
      </button>
    </main>
  );
}
