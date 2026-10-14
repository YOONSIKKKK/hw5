/** Visual identity for each agent. One colour per role, used everywhere that
 *  agent appears — avatar, name, feed rail, summary card — so an operator can
 *  track a single agent down the feed by colour alone. */
export interface AgentStyle {
  label: string;
  initials: string;
  colour: string;
  role: string;
}

export const AGENTS: Record<string, AgentStyle> = {
  boss: {
    label: "Boss",
    initials: "BO",
    colour: "#ff2d78",
    role: "Routes every ticket and makes the final call",
  },
  inventory: {
    label: "Inventory",
    initials: "IN",
    colour: "#ffb648",
    role: "Stock by SKU and size, shortages, vendors",
  },
  accounting: {
    label: "Accounting",
    initials: "AC",
    colour: "#3ddc97",
    role: "Cash, invoices, margins, payment requests",
  },
  facilities: {
    label: "Facilities",
    initials: "FA",
    colour: "#9d7cff",
    role: "The shop space, the lease and rent",
  },
  customer_service: {
    label: "Customer Service",
    initials: "CS",
    colour: "#4cc9f0",
    role: "Drafts replies — never sends",
  },
  supervisor: {
    label: "You",
    initials: "YOU",
    colour: "#f5f5f7",
    role: "The human who approves money",
  },
};

export const agentStyle = (name?: string): AgentStyle =>
  AGENTS[name ?? ""] ?? {
    label: name ?? "System",
    initials: "SY",
    colour: "#6a6a78",
    role: "",
  };

export const ORDER = ["boss", "inventory", "accounting", "facilities", "customer_service"];
