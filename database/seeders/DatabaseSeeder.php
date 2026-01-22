<?php

namespace Database\Seeders;

use App\Models\User;
use Illuminate\Database\Seeder;
use Illuminate\Support\Facades\Hash;
use Spatie\Permission\Models\Role;
use Spatie\Permission\Models\Permission;

class DatabaseSeeder extends Seeder
{
    /**
     * Seed the application's database.
     */
    public function run(): void
    {
        // =====================================================================
        // ROLES E PERMISSIONS
        // =====================================================================
        
        // Cria roles
        $adminRole = Role::firstOrCreate(['name' => 'admin', 'guard_name' => 'web']);
        $gestorRole = Role::firstOrCreate(['name' => 'gestor', 'guard_name' => 'web']);
        $userRole = Role::firstOrCreate(['name' => 'user', 'guard_name' => 'web']);

        // Cria permissions
        $permissions = [
            // Usuários
            'users.view',
            'users.create',
            'users.update',
            'users.delete',
            
            // Auditoria
            'audit.view',
            
            // Configurações
            'settings.view',
            'settings.update',
            
            // Processos
            'processos.analisar',
            'processos.gerar',
            'processos.inserir',
            'processos.assinar',
        ];

        foreach ($permissions as $permissionName) {
            Permission::firstOrCreate(['name' => $permissionName, 'guard_name' => 'web']);
        }

        // Atribui permissions aos roles
        $adminRole->syncPermissions($permissions);
        
        $gestorRole->syncPermissions([
            'users.view',
            'audit.view',
            'processos.analisar',
            'processos.gerar',
            'processos.inserir',
            'processos.assinar',
        ]);
        
        $userRole->syncPermissions([
            'processos.analisar',
            'processos.gerar',
            'processos.inserir',
            'processos.assinar',
        ]);

        // =====================================================================
        // USUÁRIO ADMIN INICIAL
        // =====================================================================
        
        $admin = User::firstOrCreate(
            ['usuario_sei' => 'admin'],
            [
                'password' => Hash::make('admin123'), // TROCAR EM PRODUÇÃO!
                'nome_completo' => 'Administrador do Sistema',
                'posto_grad' => null,
                'cargo' => 'Administrador',
                'unidade' => 'TI',
                'ativo' => true,
                'primeiro_acesso' => false, // Admin já tem senha definida
            ]
        );
        
        $admin->assignRole('admin');

        $this->command->info('✅ Roles e permissions criados');
        $this->command->info('✅ Usuário admin criado');
        $this->command->warn('⚠️  Lembre-se de trocar a senha do admin em produção!');

        // =====================================================================
        // USUÁRIOS DE EXEMPLO (apenas em ambiente de desenvolvimento)
        // =====================================================================
        
        if (app()->environment('local', 'development')) {
            $this->seedExampleUsers($userRole);
        }
    }

    /**
     * Cria usuários de exemplo para desenvolvimento.
     */
    private function seedExampleUsers(Role $userRole): void
    {
        $usuarios = [
            [
                'usuario_sei' => 'gilmar.moura',
                'nome_completo' => 'Gilmar Torres Marques Moura',
                'posto_grad' => 'MAJ QOBMEC',
                'cargo' => 'Diretor de Recursos Humanos',
                'unidade' => 'DRH',
            ],
            [
                'usuario_sei' => 'joao.silva',
                'nome_completo' => 'João da Silva Santos',
                'posto_grad' => 'CAP QOBM',
                'cargo' => 'Chefe de Seção',
                'unidade' => 'DEI',
            ],
            [
                'usuario_sei' => 'maria.oliveira',
                'nome_completo' => 'Maria Oliveira Lima',
                'posto_grad' => '1º TEN QOBM',
                'cargo' => 'Analista',
                'unidade' => 'SUBCMD',
            ],
        ];

        foreach ($usuarios as $dados) {
            $user = User::firstOrCreate(
                ['usuario_sei' => $dados['usuario_sei']],
                array_merge($dados, [
                    'password' => Hash::make('123456'), // Senha padrão para dev
                    'ativo' => true,
                    'primeiro_acesso' => true,
                ])
            );
            
            $user->assignRole($userRole);
        }

        $this->command->info('✅ Usuários de exemplo criados (ambiente dev)');
    }
}
