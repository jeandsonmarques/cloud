const { PrismaClient } = require("@prisma/client");
const bcrypt = require("bcryptjs");

const prisma = new PrismaClient();

async function main() {
  const adminEmail = "admin@demo.dev";
  const adminPassword = "demo123";

  const passwordHash = await bcrypt.hash(adminPassword, 12);

  await prisma.user.upsert({
    where: { email: adminEmail },
    update: { passwordHash, role: "admin" },
    create: {
      email: adminEmail,
      passwordHash,
      role: "admin",
    },
  });

  const layerSeeds = [
    { name: "redes_esgoto", schemaName: "public", srid: 31984, geomType: "LINESTRING" },
    { name: "pocos_bombeamento", schemaName: "public", srid: 31984, geomType: "POINT" },
    { name: "bairros", schemaName: "public", srid: 31984, geomType: "MULTIPOLYGON" },
  ];

  for (const layer of layerSeeds) {
    await prisma.layer.upsert({
      where: { name: layer.name },
      update: {
        schemaName: layer.schemaName,
        srid: layer.srid,
        geomType: layer.geomType,
      },
      create: layer,
    });
  }

  console.log("Prisma seed completed");
}

main()
  .catch((error) => {
    console.error("Failed to seed database via Prisma:", error);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
