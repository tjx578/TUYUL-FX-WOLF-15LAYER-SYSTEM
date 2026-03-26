import { permanentRedirect } from "next/navigation";

export default function PricesAliasPage(): never {
  permanentRedirect("/analysis?tab=prices");
}
