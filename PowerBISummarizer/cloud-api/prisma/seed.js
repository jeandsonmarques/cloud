const { PrismaClient } = require("@prisma/client");
const bcrypt = require("bcryptjs");

const databaseUrl = process.env.DATABASE_URL;
const adminEmail = process.env.ADMIN_EMAIL;
const adminPassword = process.env.ADMIN_PASSWORD;

if (!databaseUrl) {
  throw new Error("DATABASE_URL is required to run the Prisma seed.");
}

const prisma = new PrismaClient();

async function ensureAdminUser() {
  if (!adminEmail || !adminPassword) {
    console.log("ADMIN_EMAIL and/or ADMIN_PASSWORD not provided. Skipping admin seed.");
    return;
  }

  const passwordHash = await bcrypt.hash(adminPassword, 12);

  // Prisma model `User` maps to the `users` table (`email`, `password_hash`, `role` columns). Adjust if your schema differs.
  await prisma.user.upsert({
    where: { email: adminEmail },
    update: {
      passwordHash,
      role: "ADMIN",
    },
    create: {
      email: adminEmail,
      passwordHash,
      role: "ADMIN",
    },
  });

  console.log(`Ensured admin user ${adminEmail}`);
}

async function main() {
  await ensureAdminUser();
}

main()
  .catch((error) => {
    console.error("Failed to seed database via Prisma:", error);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
