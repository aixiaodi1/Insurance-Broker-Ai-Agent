import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "经纪人助手",
  description: "用于对话和资料查询的中文工作台。"
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
