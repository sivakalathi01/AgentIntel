"use client";

import "@rainbow-me/rainbowkit/styles.css";
import {
  RainbowKitProvider,
  getDefaultConfig,
  getDefaultWallets,
} from "@rainbow-me/rainbowkit";
import { WagmiProvider } from "wagmi";
import { QueryClientProvider, QueryClient } from "@tanstack/react-query";
import { ReactNode } from "react";

// Configure Kite testnet
const kiteChain = {
  id: 2368,
  name: "Kite Testnet",
  nativeCurrency: { name: "Ether", symbol: "ETH", decimals: 18 },
  rpcUrls: {
    default: { http: ["https://rpc-testnet.gokite.ai"] },
  },
  blockExplorers: {
    default: { name: "Kitescan", url: "https://testnet.kitescan.ai" },
  },
  testnet: true,
};

const { wallets } = getDefaultWallets();
const walletConnectProjectId = process.env.NEXT_PUBLIC_WALLETCONNECT_PROJECT_ID || "agentintel";

const config = getDefaultConfig({
  appName: "AgentIntel",
  projectId: walletConnectProjectId,
  chains: [kiteChain as any],
  wallets,
  ssr: true,
});

const queryClient = new QueryClient();

export function Providers({ children }: { children: ReactNode }) {
  return (
    <WagmiProvider config={config}>
      <QueryClientProvider client={queryClient}>
        <RainbowKitProvider>{children}</RainbowKitProvider>
      </QueryClientProvider>
    </WagmiProvider>
  );
}
