import React from "react";

function S({ size = 17, children, sw = 2 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="#c05f33"
      strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round">{children}</svg>
  );
}
function SC({ size = 20, children, sw = 2 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round">{children}</svg>
  );
}

export const LogoIcon = ({ size = 34 }) => (
  <S size={size} sw={1.8}><rect x="3" y="4" width="18" height="7" rx="2" /><rect x="3" y="13" width="18" height="7" rx="2" /><path d="M7 7.5h.01M7 16.5h.01" /></S>
);
export const LockIcon = () => (
  <SC size={18}><rect x="4" y="10" width="16" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></SC>
);
export const RefreshIcon = () => (
  <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="#3d2c22" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36" /><path d="M21 3v6h-6" /></svg>
);
export const LogoutIcon = () => (
  <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="#3d2c22" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><path d="M16 17l5-5-5-5" /><path d="M21 12H9" /></svg>
);
export const CpuIcon = () => (
  <S size={15}><rect x="5" y="5" width="14" height="14" rx="2" /><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3" /></S>
);
export const RamIcon = () => (
  <S size={15}><rect x="3" y="7" width="18" height="10" rx="2" /><path d="M7 11v2M11 11v2M15 11v2" /></S>
);
export const TempIcon = () => (
  <S size={15}><path d="M12 3v11" /><path d="M8.5 10.5a5 5 0 1 0 7 0" /></S>
);
export const ClockIcon = () => (
  <S size={15}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 3" /></S>
);
export const DiskIcon = () => (
  <S size={17}><ellipse cx="12" cy="5.5" rx="8" ry="3" /><path d="M4 5.5v13c0 1.66 3.58 3 8 3s8-1.34 8-3v-13" /><path d="M4 12c0 1.66 3.58 3 8 3s8-1.34 8-3" /></S>
);
export const GlobeIcon = () => (
  <S size={17}><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c2.5 2.6 3.9 5.7 3.9 9S14.5 18.4 12 21c-2.5-2.6-3.9-5.7-3.9-9S9.5 5.6 12 3z" /></S>
);
export const PulseIcon = () => (
  <S size={17}><path d="M3 12h4l2.5-6 4 12L16 12h5" /></S>
);
export const FolderIcon = () => (
  <S size={17}><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /></S>
);
export const GridIcon = () => (
  <S size={17}><rect x="3" y="3" width="7.5" height="7.5" rx="2" /><rect x="13.5" y="3" width="7.5" height="7.5" rx="2" /><rect x="3" y="13.5" width="7.5" height="7.5" rx="2" /><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="2" /></S>
);
export const BagIcon = () => (
  <S size={17}><path d="M4 7V6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v1" /><path d="M3 7h18l-1.2 12a2 2 0 0 1-2 1.8H6.2a2 2 0 0 1-2-1.8z" /><path d="M9 11a3 3 0 0 0 6 0" /></S>
);
export const SlidersIcon = () => (
  <S size={17}><path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3" /><path d="M1 14h6M9 8h6M17 16h6" /></S>
);
export const FileTextIcon = () => (
  <S size={17}><path d="M6 2h9l5 5v15H6z" /><path d="M14 2v6h6" /><path d="M9 13h6M9 17h6" /></S>
);
export const GearIcon = () => (
  <S size={17}><circle cx="12" cy="12" r="3.2" /><path d="M19 12a7 7 0 0 0-.14-1.4l2-1.55-2-3.46-2.36.95A7 7 0 0 0 14.1 5.1L13.7 2.6h-3.4L9.9 5.1a7 7 0 0 0-2.4 1.44l-2.36-.95-2 3.46 2 1.55a7 7 0 0 0 0 2.8l-2 1.55 2 3.46 2.36-.95a7 7 0 0 0 2.4 1.44l.4 2.5h3.4l.4-2.5a7 7 0 0 0 2.4-1.44l2.36.95 2-3.46-2-1.55c.1-.46.14-.93.14-1.4z" /></S>
);
export const PowerIcon = () => (
  <S size={17}><path d="M12 3v9" /><path d="M6.3 6.5a8 8 0 1 0 11.4 0" /></S>
);
export const UploadIcon = () => (
  <SC size={15}><path d="M12 17V4" /><path d="M6 10l6-6 6 6" /><path d="M4 21h16" /></SC>
);
export const RebootIcon = () => (
  <SC size={17}><path d="M21 12a9 9 0 1 1-2.64-6.36" /><path d="M21 3v6h-6" /></SC>
);
export const PowerBtnIcon = () => (
  <SC size={17}><path d="M12 3v9" /><path d="M6.3 6.5a8 8 0 1 0 11.4 0" /></SC>
);
export const FileRowIcon = () => (
  <S size={19}><path d="M6 2h9l5 5v15H6z" /><path d="M14 2v6h6" /></S>
);
export const FolderRowIcon = () => (
  <S size={19}><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /></S>
);

/* ikon navigasi bawah */
export const NavHome = () => (<SC><path d="M3 11l9-8 9 8" /><path d="M5 9.5V21h14V9.5" /></SC>);
export const NavFiles = () => (<SC><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /></SC>);
export const NavApps = () => (<SC><rect x="3" y="3" width="7.5" height="7.5" rx="2" /><rect x="13.5" y="3" width="7.5" height="7.5" rx="2" /><rect x="3" y="13.5" width="7.5" height="7.5" rx="2" /><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="2" /></SC>);
export const NavSvc = () => (<SC><path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3" /><path d="M1 14h6M9 8h6M17 16h6" /></SC>);
export const NavSys = () => (<SC><circle cx="12" cy="12" r="3.2" /><path strokeWidth="1.4" d="M12 2.8l.9 2.7 2.3-.9 1 2.6 2.9.3-.5 2.9 2.2 1.9-1.9 2.2.9 2.8-2.9.6-1 2.6-2.8-1.1L12 21.2l-1.1-2.6-2.8 1.1-1-2.6-2.9-.6.9-2.8L3.2 11.5l2.2-1.9-.5-2.9 2.9-.3 1-2.6 2.3.9z" /></SC>);

/* ikon per aplikasi */
export const APP_ICONS = {
  filebrowser: <S size={19}><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /></S>,
  syncthing: <S size={19}><path d="M20 12a8 8 0 0 1-14.2 5.1" /><path d="M4 12a8 8 0 0 1 14.2-5.1" /><path d="M18.5 2.5v4h-4" /><path d="M5.5 21.5v-4h4" /></S>,
  qbittorrent: <S size={19}><path d="M12 4v10" /><path d="M6 10l6 6 6-6" /><path d="M4 20h16" /></S>,
  "uptime-kuma": <S size={19}><path d="M3 12h4l2.5-6 4 12L16 12h5" /></S>,
  adguard: <S size={19}><path d="M12 3l7 3v5c0 4.6-3 8.4-7 10-4-1.6-7-5.4-7-10V6z" /><path d="M9.5 12l2 2 3.5-4" /></S>,
  vaultwarden: <S size={19}><rect x="4" y="10" width="16" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /><circle cx="12" cy="15.5" r="1.6" /></S>,
  jellyfin: <S size={19}><rect x="3" y="5" width="18" height="14" rx="3" /><path d="M10.5 9.5l5 2.5-5 2.5z" /></S>,
};
