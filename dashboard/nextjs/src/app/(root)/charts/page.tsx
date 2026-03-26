import { permanentRedirect } from "next/navigation";

export default function ChartsAliasPage(): never {
  permanentRedirect("/analysis?tab=charts");
}
