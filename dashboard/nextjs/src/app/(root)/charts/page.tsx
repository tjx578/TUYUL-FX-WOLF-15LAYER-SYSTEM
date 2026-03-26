import { permanentRedirect } from "next/navigation";

export default function ChartsAliasPage() {
  permanentRedirect("/analysis?tab=charts");
}
