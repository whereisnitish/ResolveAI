import { ErrorState } from "@/components/error-state";

export default function NotFound() {
  return (
    <ErrorState title="Page not found" description="The page you're looking for doesn't exist or has been moved." />
  );
}
