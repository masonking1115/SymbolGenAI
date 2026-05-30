type Props = { size?: number; className?: string };

const stroke = (props: Props) => ({
  width: props.size ?? 18,
  height: props.size ?? 18,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  className: props.className,
});

export const I = {
  Schematic: (p: Props = {}) => (
    <svg {...stroke(p)}>
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M7 9h4M13 9h4M7 15h4M13 15h4M11 9v6M13 9v6" />
    </svg>
  ),
  Library: (p: Props = {}) => (
    <svg {...stroke(p)}>
      <path d="M4 5h6v14H4zM14 5h6v14h-6z" />
      <path d="M7 9h.01M17 9h.01" />
    </svg>
  ),
  Review: (p: Props = {}) => (
    <svg {...stroke(p)}>
      <path d="M9 11l2 2 5-5" />
      <rect x="3" y="3" width="18" height="18" rx="2" />
    </svg>
  ),
  Bom: (p: Props = {}) => (
    <svg {...stroke(p)}>
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M3 9h18M9 3v18" />
    </svg>
  ),
  Sidebar: (p: Props = {}) => (
    <svg {...stroke(p)}>
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M9 3v18" />
    </svg>
  ),
  Back: (p: Props = {}) => (
    <svg {...stroke(p)}>
      <path d="M15 6l-6 6 6 6" />
    </svg>
  ),
  Forward: (p: Props = {}) => (
    <svg {...stroke(p)}>
      <path d="M9 6l6 6-6 6" />
    </svg>
  ),
  Flag: (p: Props = {}) => (
    <svg {...stroke(p)}>
      <path d="M5 21V4h13l-2 4 2 4H5" />
    </svg>
  ),
  History: (p: Props = {}) => (
    <svg {...stroke(p)}>
      <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
      <path d="M3 3v5h5M12 7v5l3 2" />
    </svg>
  ),
  Bell: (p: Props = {}) => (
    <svg {...stroke(p)}>
      <path d="M18 16V11a6 6 0 1 0-12 0v5l-2 2h16z" />
      <path d="M10 20a2 2 0 0 0 4 0" />
    </svg>
  ),
  Search: (p: Props = {}) => (
    <svg {...stroke(p)}>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-4-4" />
    </svg>
  ),
  Plus: (p: Props = {}) => (
    <svg {...stroke(p)}>
      <path d="M12 5v14M5 12h14" />
    </svg>
  ),
  Caret: (p: Props = {}) => (
    <svg {...stroke(p)}>
      <path d="M6 9l6 6 6-6" />
    </svg>
  ),
  Dots: (p: Props = {}) => (
    <svg {...stroke(p)}>
      <circle cx="5" cy="12" r="1" />
      <circle cx="12" cy="12" r="1" />
      <circle cx="19" cy="12" r="1" />
    </svg>
  ),
  Folder: (p: Props = {}) => (
    <svg {...stroke(p)}>
      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
    </svg>
  ),
  Check: (p: Props = {}) => (
    <svg {...stroke(p)}>
      <path d="M5 12l5 5L20 7" />
    </svg>
  ),
  X: (p: Props = {}) => (
    <svg {...stroke(p)}>
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  ),
  Dot: (p: Props = {}) => (
    <svg {...stroke(p)}>
      <circle cx="12" cy="12" r="4" />
    </svg>
  ),
  Refresh: (p: Props = {}) => (
    <svg {...stroke(p)}>
      <path d="M21 12a9 9 0 1 1-3-6.7L21 8" />
      <path d="M21 3v5h-5" />
    </svg>
  ),
  Play: (p: Props = {}) => (
    <svg {...stroke(p)}>
      <path d="M6 4l14 8-14 8z" />
    </svg>
  ),
  Wrench: (p: Props = {}) => (
    <svg {...stroke(p)}>
      <path d="M14 7a4 4 0 1 1-4 4l-6 6 3 3 6-6a4 4 0 0 1 4-4" />
    </svg>
  ),
  Wave: (p: Props = {}) => (
    <svg {...stroke(p)}>
      <path d="M2 12h3l2-7 4 14 3-9 2 4h6" />
    </svg>
  ),
  Resources: (p: Props = {}) => (
    <svg {...stroke(p)}>
      <path d="M12 3 3 7.5 12 12l9-4.5L12 3z" />
      <path d="M3 12l9 4.5L21 12" />
      <path d="M3 16.5 12 21l9-4.5" />
    </svg>
  ),
  Datasheet: (p: Props = {}) => (
    <svg {...stroke(p)}>
      <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
      <path d="M14 3v6h6" />
      <path d="M8 13h8M8 17h8M8 9h2" />
    </svg>
  ),
  Upload: (p: Props = {}) => (
    <svg {...stroke(p)}>
      <path d="M12 16V4M7 9l5-5 5 5" />
      <path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
    </svg>
  ),
  External: (p: Props = {}) => (
    <svg {...stroke(p)}>
      <path d="M14 4h6v6M20 4l-9 9" />
      <path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4" />
    </svg>
  ),
  Trash: (p: Props = {}) => (
    <svg {...stroke(p)}>
      <path d="M4 7h16M10 11v6M14 11v6" />
      <path d="M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13M9 7V4h6v3" />
    </svg>
  ),
  Diff: (p: Props = {}) => (
    <svg {...stroke(p)}>
      <rect x="3" y="3" width="8" height="18" rx="1" />
      <rect x="13" y="3" width="8" height="18" rx="1" />
      <path d="M5 9h4M5 13h4M15 9h4M15 13h4M15 17h4" />
    </svg>
  ),
  Terminal: (p: Props = {}) => (
    <svg {...stroke(p)}>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M7 9l3 3-3 3M13 15h4" />
    </svg>
  ),
};
