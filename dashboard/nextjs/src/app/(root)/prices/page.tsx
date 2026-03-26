import { permanentRedirect } from "next/navigation";

export default function PricesAliasPage() {
  permanentRedirect("/analysis?tab=prices");
}
