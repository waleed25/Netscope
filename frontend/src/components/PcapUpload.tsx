import { useCallback, useState } from "react";
import { useStore } from "../store/useStore";
import { uploadPcap, fetchPackets, fetchInsights } from "../lib/api";
import { Upload, FileText, CheckCircle, XCircle, Loader2 } from "lucide-react";

type UploadState = "idle" | "uploading" | "success" | "error";

export function PcapUpload() {
  const { setPackets, addInsight, setPacketsSubTab } = useStore();
  const [uploadState, setUploadState] = useState<UploadState>("idle");
  const [dragOver, setDragOver] = useState(false);
  const [result, setResult] = useState<{ filename: string; packet_count: number } | null>(null);
  const [error, setError] = useState("");

  const handleFile = useCallback(async (file: File) => {
    setUploadState("uploading");
    setError("");
    setResult(null);

    try {
      const res = await uploadPcap(file);
      const data = res.data;
      setResult({ filename: data.filename, packet_count: data.packet_count });

      // Load packets into store
      const { packets } = await fetchPackets(0, 5000);
      setPackets(packets);

      setUploadState("success");

      // Load generated insights in background — don't fail upload if LLM is offline
      fetchInsights()
        .then((insights) => insights.forEach((i) => addInsight(i)))
        .catch(() => {/* Ollama/LLM offline — insights skipped */});
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Upload failed.");
      setUploadState("error");
    }
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile]
  );

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
    e.target.value = "";
  };

  const viewPackets = () => setPacketsSubTab("live");
  const viewInsights = () => setPacketsSubTab("live");

  return (
    <div className="flex flex-col items-center justify-center h-full px-6 py-10 gap-6">
      <div className="max-w-lg w-full">
        <h2 className="text-foreground font-semibold text-sm mb-1">Upload .pcap File</h2>
        <p className="text-muted text-xs mb-4">
          Upload a Wireshark .pcap, .pcapng, or .cap file to analyze it offline with the AI agent.
        </p>

        {/* Drop zone */}
        <label
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          className={`flex flex-col items-center justify-center w-full h-48 border-2 border-dashed rounded-xl cursor-pointer transition-colors ${
            dragOver
              ? "border-accent bg-accent/5"
              : "border-border bg-surface hover:border-muted-dim"
          }`}
        >
          <input
            type="file"
            accept=".pcap,.pcapng,.cap"
            onChange={handleInputChange}
            className="hidden"
          />
          {uploadState === "idle" && (
            <>
              <Upload className="w-8 h-8 text-muted mb-3" />
              <p className="text-foreground text-sm font-medium">Drop a .pcap file here</p>
              <p className="text-muted text-xs mt-1">or click to browse</p>
              <p className="text-muted-dim text-xs mt-3">.pcap · .pcapng · .cap</p>
            </>
          )}
          {uploadState === "uploading" && (
            <>
              <Loader2 className="w-8 h-8 text-accent animate-spin mb-3" />
              <p className="text-foreground text-sm">Parsing packets...</p>
            </>
          )}
          {uploadState === "success" && result && (
            <>
              <CheckCircle className="w-8 h-8 text-success mb-3" />
              <p className="text-success text-sm font-medium">Upload successful</p>
              <p className="text-muted text-xs mt-1">{result.filename}</p>
              <p className="text-foreground text-xs mt-1 font-semibold">
                {result.packet_count.toLocaleString()} packets parsed
              </p>
            </>
          )}
          {uploadState === "error" && (
            <>
              <XCircle className="w-8 h-8 text-danger mb-3" />
              <p className="text-danger text-sm font-medium">Upload failed</p>
              <p className="text-muted text-xs mt-1">{error}</p>
            </>
          )}
        </label>

        {/* Actions after success */}
        {uploadState === "success" && (
          <div className="flex gap-3 mt-4">
            <button
              onClick={viewPackets}
              className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-success-emphasis hover:bg-success-emphasis-hover text-white text-xs rounded font-medium transition-colors"
            >
              <FileText className="w-3.5 h-3.5" />
              View Packets
            </button>
            <button
              onClick={viewInsights}
              className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-purple-emphasis hover:bg-purple-emphasis-hover text-white text-xs rounded font-medium transition-colors"
            >
              View AI Insights
            </button>
          </div>
        )}

        {/* Retry */}
        {uploadState === "error" && (
          <button
            onClick={() => setUploadState("idle")}
            className="mt-4 w-full px-4 py-2 border border-border text-muted hover:text-foreground text-xs rounded transition-colors"
          >
            Try again
          </button>
        )}
      </div>
    </div>
  );
}
