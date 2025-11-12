import { PrismaClient } from '@prisma/client';
import bcrypt from 'bcryptjs';

const prisma = new PrismaClient();

async function main() {
  const email = process.env.ADMIN_EMAIL || 'admin@local';
  const plain = process.env.ADMIN_PASSWORD || 'admin123!';
  const role  = 'ADMIN';

  const hash = bcrypt.hashSync(plain, 10);

  // ===== Ajuste aqui se o nome da tabela/colunas forem diferentes =====
  // Por padrão, assume tabela "users" com colunas: email, password_hash, role.
  // Se seu model for "User" (U maiúsculo), troque prisma.users por prisma.user.
  // Se a coluna for "passwordHash", troque o campo no create/update.
  const upserted = await prisma.users.upsert({
    where: { email },
    update: { password_hash: hash, role },
    create: { email, password_hash: hash, role }
  });
  // ===================================================================

  console.log('Admin OK:', { id: upserted.id, email: upserted.email, role: upserted.role });
}

main()
  .catch((e) => {
    console.error('Seed error:', e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
