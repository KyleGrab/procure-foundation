import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { FileSearch } from "lucide-react";
import { ProcurementToolCard } from "./ProcurementToolCard";

describe("ProcurementToolCard", () => {
  it("renders title, description, and a working action link - no card is ever a dead end", () => {
    render(
      <ProcurementToolCard
        icon={FileSearch}
        title="Price Reviews"
        description="Compare supplier price lists."
        action={{ label: "View Price Reviews", href: "/price-reviews" }}
      />
    );
    expect(screen.getByText("Price Reviews")).toBeInTheDocument();
    expect(screen.getByText("Compare supplier price lists.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /View Price Reviews/ })).toHaveAttribute("href", "/price-reviews");
  });

  it("renders no badge and no reason when neither is supplied", () => {
    render(
      <ProcurementToolCard
        icon={FileSearch}
        title="Price Reviews"
        description="Compare supplier price lists."
        action={{ label: "View Price Reviews", href: "/price-reviews" }}
      />
    );
    expect(screen.queryByText("Illustrative")).not.toBeInTheDocument();
    expect(screen.queryByText("Data required")).not.toBeInTheDocument();
  });

  it("shows the illustrative badge when marked illustrative", () => {
    render(
      <ProcurementToolCard
        icon={FileSearch}
        title="Supplier Changes"
        description="Illustrative Supplier Co.'s latest submission."
        badge="illustrative"
        action={{ label: "Open illustrative walkthrough", href: "/price-reviews/demo" }}
      />
    );
    expect(screen.getByText("Illustrative")).toBeInTheDocument();
  });

  it("states the honest reason an unavailable tool isn't connected, and still links somewhere real", () => {
    render(
      <ProcurementToolCard
        icon={FileSearch}
        title="Contracts"
        description="Contract lifecycle, escalation, and renewal tracking."
        badge="unavailable"
        unavailableReason="Not connected — requires live contract data."
        action={{ label: "Open Contracts workspace", href: "/dashboard/contracts" }}
      />
    );
    expect(screen.getByText("Data required")).toBeInTheDocument();
    expect(screen.getByText("Not connected — requires live contract data.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open Contracts workspace/ })).toHaveAttribute(
      "href",
      "/dashboard/contracts"
    );
  });
});
