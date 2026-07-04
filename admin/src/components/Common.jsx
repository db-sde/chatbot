import { Loader2, Inbox, AlertTriangle } from "lucide-react";

export function Badge({ variant = "neutral", children }) {
  const styles = {
    neutral: "bg-gray-800 text-gray-300 border-gray-700",
    primary: "bg-blue-950/40 text-blue-400 border-blue-900/50",
    success: "bg-emerald-950/40 text-emerald-400 border-emerald-900/50",
    warning: "bg-amber-950/40 text-amber-400 border-amber-900/50",
    danger: "bg-red-950/40 text-red-400 border-red-900/50",
  };

  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold border ${styles[variant] || styles.neutral}`}>
      {children}
    </span>
  );
}

export function LoadingState({ message = "Loading data from catalog..." }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-4">
      <Loader2 size={36} className="text-blue-500 animate-spin" />
      <span className="text-gray-400 text-sm font-medium mt-4">{message}</span>
    </div>
  );
}

export function EmptyState({ title = "No data found", description = "No items match your query right now.", icon: Icon = Inbox }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-4 text-center bg-[#111827] border border-[#1F2937] rounded-xl">
      <div className="p-3 bg-[#1D2433] rounded-full text-gray-400 border border-[#2D3748] mb-4">
        <Icon size={24} />
      </div>
      <h3 className="text-base font-semibold text-gray-200">{title}</h3>
      <p className="text-xs text-gray-500 max-w-sm mt-2">{description}</p>
    </div>
  );
}

export function ErrorState({ title = "Query failed", description = "Failed to load data from API endpoints. Try checking your admin token.", retry }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 px-4 text-center bg-red-950/10 border border-red-950/40 rounded-xl">
      <div className="p-3 bg-red-950/30 rounded-full text-red-400 border border-red-900/30 mb-4 animate-pulse">
        <AlertTriangle size={24} />
      </div>
      <h3 className="text-base font-semibold text-red-400">{title}</h3>
      <p className="text-xs text-red-500 max-w-sm mt-2">{description}</p>
      {retry && (
        <button
          onClick={retry}
          className="mt-4 px-4 py-2 bg-red-950 text-red-400 border border-red-900 rounded-lg text-xs font-semibold hover:bg-red-900/30 hover:text-red-300 transition-colors"
        >
          Try Again
        </button>
      )}
    </div>
  );
}
