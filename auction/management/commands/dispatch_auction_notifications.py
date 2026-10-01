from django.core.management.base import BaseCommand
from auction.scheduled_dispatch import dispatch_due_auction_emails


class Command(BaseCommand):
    help = 'Dispatches due auction notifications (24h starting soon, started notice, ended/billing).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=20,
            help='Maximum number of auctions to process per dispatch run.',
        )

    def handle(self, *args, **options):
        limit = options.get('limit', 20)
        self.stdout.write(f'Checking for due auction notifications (limit={limit})...')
        dispatched = dispatch_due_auction_emails(limit=limit)
        self.stdout.write(self.style.SUCCESS(f'Dispatched notifications for {dispatched} auction(s).'))
