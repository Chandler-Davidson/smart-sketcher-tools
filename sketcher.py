from image_pipeline import ImageValidationError, image_path_to_rgb565_lines
import asyncclick as click
from progress.bar import Bar
from projector import DeviceNotFoundError, ProjectorClient

delay_between_image_lines = 0.05


@click.group()
@click.option('--adr', help='BT address of device e.g. 11:22:33:44:55:66')
@click.pass_context
async def cli(ctx,adr):
    '''example usage: sketcher.py --adr 11:22:33:44:55:66 sendimage'''
    ctx.ensure_object(dict)

    ctx.obj['adr'] = adr
    pass

@cli.command()
@click.pass_context
@click.argument('filename',type=click.Path(exists=True))
async def sendimage(ctx,filename):

    adr = ctx.obj['adr']

    try:
        lines = image_path_to_rgb565_lines(filename, fit_mode="stretch")
    except ImageValidationError as exc:
        print(f"Could not prepare image: {exc}")
        raise click.Abort() from exc

    if adr is None:
        print("BT Address not given. Scanning for device instead...")

    bar = Bar('Sending image data', max=128,suffix="%(index)d / %(max)d Lines")
    client = ProjectorClient(line_delay_seconds=delay_between_image_lines)

    def on_progress(sent: int, total: int) -> None:
        bar.next()

    try:
        used_address = await client.send_image_lines(
            lines,
            address=adr,
            progress_callback=on_progress,
        )
    except DeviceNotFoundError as exc:
        print(str(exc))
        raise click.Abort() from exc

    print(f"\r\nDone (sent to {used_address})")

if __name__ == '__main__':
    cli()