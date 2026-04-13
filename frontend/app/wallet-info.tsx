"use client";

import { useAccount } from "wagmi";
import { useEffect, useState } from "react";

export function WalletInfo() {
  const { address, isConnected } = useAccount();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) return null;

  if (!isConnected) {
    return (
      <div className="walletInfo">
        <p>Connect your wallet to sign sessions</p>
      </div>
    );
  }

  return (
    <div className="walletInfo">
      <p>Connected Wallet: <code>{address?.slice(0, 6)}...{address?.slice(-4)}</code></p>
      <p style={{ fontSize: "0.85rem", color: "#666" }}>
        Use this wallet to sign research sessions for enhanced security
      </p>
    </div>
  );
}
