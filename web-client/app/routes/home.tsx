import type { Route } from "./+types/home";

export function meta({}: Route.MetaArgs) {
  return [
    { title: "OLIM" },
    { name: "description", content: "OLIM Web Client" },
  ];
}

export default function Home() {
  return <h1 className="text-2xl text-center mt-40">Comming Soon</h1>;
}
