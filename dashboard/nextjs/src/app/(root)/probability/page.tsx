import { permanentRedirect } from "next/navigation";

export default function ProbabilityAliasPage(): never {
  permanentRedirect("/analysis?tab=probability");
}
