#!/bin/bash
# ============================================================
# TUYUL FX Wolf-15 Dashboard — Architecture V2 Cleanup Script
# Jalankan script ini sekali dari folder dashboard/nextjs/
# untuk menyelesaikan migrasi ke arsitektur baru (6 halaman)
# ============================================================

set -e

NEXTJS_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$NEXTJS_DIR/src/app"

echo "📁 Working in: $NEXTJS_DIR"
echo ""

# ── STEP 1: Hapus (main) route group — sudah dipindahkan ke (control) dan (root) ──
echo "🗑️  Menghapus app/(main)/ route group (sudah digantikan oleh (control) dan (root))..."
rm -rf "$SRC/(main)"
echo "   ✓ (main) dihapus"

# ── STEP 2: Hapus route lama yang sudah digabung ke halaman baru ──
echo ""
echo "🗑️  Menghapus route lama yang sudah digabung..."

# Cockpit → sudah ada di Dashboard
rm -rf "$SRC/(root)/cockpit"
echo "   ✓ /cockpit dihapus (digabung ke Dashboard)"

# Pipeline → sudah ada sebagai tab di /signals
rm -rf "$SRC/(root)/pipeline"
echo "   ✓ /pipeline dihapus (tab di /signals)"

# Probability → sudah ada sebagai confidence indicator di /signals
rm -rf "$SRC/(root)/probability"
echo "   ✓ /probability dihapus (tab di /signals)"

# Prices → sudah ada sebagai Watchlist tab di /market
rm -rf "$SRC/(root)/prices"
echo "   ✓ /prices dihapus (Watchlist tab di /market)"

# Calendar → sudah ada sebagai tab di /market
rm -rf "$SRC/(root)/calendar"
echo "   ✓ /calendar dihapus (tab di /market)"

# Architecture Audit → dev tool, tidak relevan di production
rm -rf "$SRC/(root)/architecture-audit"
echo "   ✓ /architecture-audit dihapus (dev tool)"

# Old charts route (redirect) → sudah ada di /market
rm -rf "$SRC/(root)/charts"
echo "   ✓ /charts redirect dihapus (digabung ke /market)"

# Dashboard deprecated redirect → tidak diperlukan
rm -rf "$SRC/(root)/dashboard"
echo "   ✓ /dashboard redirect dihapus"

# (root)/page.tsx deprecated file
rm -f "$SRC/(root)/page.tsx"
echo "   ✓ (root)/page.tsx deprecated dihapus"

# Accounts → sudah ada sebagai tab di /risk
rm -rf "$SRC/(control)/accounts"
echo "   ✓ /accounts dihapus (tab di /risk)"

# EA Manager → sudah ada sebagai tab di /settings
rm -rf "$SRC/(control)/ea-manager"
echo "   ✓ /ea-manager dihapus (tab di /settings)"

# Prop-Firm → sudah ada sebagai tab di /risk
rm -rf "$SRC/(control)/prop-firm"
echo "   ✓ /prop-firm dihapus (tab di /risk)"

# News → sudah ada sebagai tab di /market
rm -rf "$SRC/(control)/news"
echo "   ✓ /news dihapus (tab di /market)"

# Journal → sudah ada sebagai tab di /trades
rm -rf "$SRC/(control)/journal"
echo "   ✓ /journal dihapus (tab di /trades)"

# Analysis → sudah ada di /market
rm -rf "$SRC/(control)/analysis"
echo "   ✓ /analysis dihapus (tab di /market)"

# Admin routes → sudah ada sebagai tab di /settings
rm -rf "$SRC/(admin)"
echo "   ✓ (admin)/ dihapus (tab Audit di /settings)"

# ── STEP 3: Hapus (control)/market konflik dengan (root)/market ──
rm -rf "$SRC/(main)/market"
echo "   ✓ (main)/market stub dihapus"

# ── STEP 4: Hapus (control)/page.tsx (command center parent) ──
rm -f "$SRC/(control)/page.tsx"
echo "   ✓ /control parent page dihapus"

# ── STEP 5: Summary ──
echo ""
echo "✅ Cleanup selesai! Struktur halaman baru:"
echo ""
echo "   /           → Dashboard (app/(main)/page.tsx)"
echo "   /signals    → Signals (app/(control)/signals/page.tsx)"
echo "   /trades     → Trades  (app/(control)/trades/page.tsx)"
echo "   /risk       → Risk & Compliance (app/(control)/risk/page.tsx)"
echo "   /market     → Market (app/(root)/market/page.tsx)"
echo "   /settings   → Settings & Ops (app/(control)/settings/page.tsx)"
echo "   /login      → Login"
echo ""
echo "   Total: 6 halaman utama dari sebelumnya 22 halaman."
echo ""
echo "📦 Sekarang jalankan: npm run build"
