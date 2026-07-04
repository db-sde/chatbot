export default function StatsCard({ title, value, subtext, icon: Icon, trend, trendType = "neutral", loading }) {
  if (loading) {
    return (
      <div className="bg-[#111827] border border-[#1F2937] rounded-xl p-6 animate-pulse">
        <div className="flex justify-between items-start">
          <div className="h-4 bg-[#1F2937] w-24 rounded"></div>
          <div className="h-8 w-8 bg-[#1F2937] rounded-lg"></div>
        </div>
        <div className="h-8 bg-[#1F2937] w-32 rounded mt-4"></div>
        <div className="h-3 bg-[#1F2937] w-40 rounded mt-2"></div>
      </div>
    );
  }

  const getTrendColor = () => {
    if (trendType === "positive") return "text-emerald-500 bg-emerald-950/30 border-emerald-800/30";
    if (trendType === "negative") return "text-red-500 bg-red-950/30 border-red-800/30";
    return "text-gray-400 bg-gray-900 border-gray-800";
  };

  return (
    <div className="bg-[#111827] border border-[#1F2937] rounded-xl p-6 transition-all hover:border-[#2D3748] shadow-sm">
      <div className="flex justify-between items-start">
        <h3 className="text-sm font-medium text-gray-400 truncate">{title}</h3>
        {Icon && (
          <div className="p-2 bg-[#1F2937] rounded-lg text-gray-300 border border-[#2D3748]">
            <Icon size={18} />
          </div>
        )}
      </div>

      <div className="mt-4 flex items-baseline gap-2">
        <span className="text-2xl font-bold text-gray-100 tracking-tight">{value}</span>
        {trend && (
          <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${getTrendColor()}`}>
            {trend}
          </span>
        )}
      </div>

      {subtext && (
        <p className="text-xs text-gray-500 mt-2 font-medium">{subtext}</p>
      )}
    </div>
  );
}
